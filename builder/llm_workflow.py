"""General mode: Claude writes the Freya workflow directly from the case documents.

Used when the case is not the collections pattern the deterministic generator knows (no bank tool API file in the
inputs, a mock URL instead). The builder still owns everything around the model: the documents it reads, the
platform rules it hands over, validation (local checks + Freya dry run) with a repair loop, saving, the agent
settings, the self-test and the export.
"""
import json, os, pathlib, re, subprocess, types

import anthropic

HERE = pathlib.Path(__file__).resolve().parent
KIT = HERE.parent
MODEL = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")

RULES = """Rules for the workflow you write (learned on this platform; follow all of them):
- Output ONE JSON object: the workflow (keys: initial_node, system_prompt, nodes, global_nodes, tools (optional), test_variables). No agent_config. No null values anywhere.
- Node types: conversation (task_message, tools, extraction_schema, transitions), api_request (pre_actions, node-level response_mapping, passthrough), code (pre_actions with a code_exec function, passthrough), end_call (terminal).
- tools only on conversation nodes; pre_actions only on api_request/code nodes. Every passthrough node ends with an "always" transition and has passthrough_default_transition.
- Every api_call tool: parameters.properties has url (default = the full URL), method (default), headers (Content-Type default application/json), and body (or for GET, query fields in the URL with {{var}}). Each body field is a leaf under body.properties with its own "default": a call variable like "{{customerNumber}}" is baked; a field the model must fill uses "default": "{{<field>}}" with type/description/enum on the leaf.
- Mapping paths start with "data." (the API body is under data). Booleans arrive as strings: test both "true" and "True", or better write string flags from code.
- Code (code_exec): read and write variables through vars.get(...) / vars[...]; wrap everything in try/except; never write "{{" or "}}" in code; do date arithmetic and formatting in code and give the model finished facts as text (put them into prompts with {{var}}).
- A model-called code_exec tool may take arguments: they arrive in a dict named `params`, and the value the code returns (return {...}) is the tool result the model reads. Use it for checks the model must not do by itself (dates, eligibility, amounts).
- Post-hooks (post_process_code on api_call tools): `result` is the envelope {status, data, status_code}; add result['data']['what_to_do_next'] = '<plain instruction>' so the model knows what to say next; result.pop('header', None).
- After every tool result the model must speak or call the next tool; tell it so in the system prompt. One tool per message.
- Transitions: deterministic variable conditions inside {"logic":"or","conditions":[...]}; AND as a nested group; "always" as {"operator":"always"}. Leave a node on a tool result or a code flag, not on what the caller said, wherever possible. Tool-call transitions (is_tool_call: true) let the model end or switch on purpose.
- end_call nodes: on_enter silent, terminal function handler __function__:end_call with message_mode "custom" and spoken_message (the farewell; {{var}} works), transitions [], disable_inactivity_monitor true.
- Keep every turn short. Say amounts and dates the way a person says them in the call language. Never invent facts: every figure comes from a tool result.
- Callers talk like people (numbers in two parts, corrections, small talk, questions back, numbers in words). Use the corrected value; a cut-off message is not an answer.
- Use on_enter {"type":"tts","text":"..."} for fixed sentences the documents require word for word.
- Set max_node_turns (e.g. 40) and max_turn_transition on conversation nodes.
"""


def _client():
    return anthropic.Anthropic(max_retries=4)


def _ask(trace, purpose, system, content, effort="high", max_tokens=128000):
    try:
        return _ask_once(trace, purpose, system, content, effort, max_tokens)
    except ValueError as e:
        # The answer ran out of room (long thinking) or had no JSON: ask again with less thinking.
        trace.event("model_retry", purpose=purpose, reason=str(e)[:200])
        return _ask_once(trace, purpose + " (retry)", system, content, "low", max_tokens)


def _ask_cli(system, content, effort):
    """BUILDER_BACKEND=cli: run the prompt through a logged-in Claude Code CLI (`claude -p`) instead of the API key."""
    exe = os.environ.get("CLAUDE_CLI", "claude")
    prompt = "\n\n".join(c["text"] for c in content)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    r = subprocess.run([exe, "-p", "--model", MODEL, "--output-format", "json", "--max-turns", "1",
                        "--effort", effort, "--system-prompt", system, "--tools", ""],
                       input=prompt, capture_output=True, text=True, env=env, timeout=3600)
    out = json.loads(r.stdout or "{}")
    if out.get("is_error") or not out.get("result"):
        raise RuntimeError(f"claude cli failed: {(out.get('result') or r.stderr or r.stdout)[:500]}")
    u = out.get("usage") or {}
    usage = types.SimpleNamespace(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0))
    return out["result"], usage


def _ask_once(trace, purpose, system, content, effort, max_tokens):
    if os.environ.get("BUILDER_BACKEND") == "cli":
        text, usage = _ask_cli(system, content, effort)
        trace.model_call(MODEL + " (claude cli)", purpose, usage)
        m = re.search(r"```json\s*(.*?)```", text, re.S)
        raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
        return json.loads(raw), text
    with _client().messages.stream(model=MODEL, max_tokens=max_tokens, system=system,
                                   thinking={"type": "adaptive"}, output_config={"effort": effort},
                                   messages=[{"role": "user", "content": content}]) as stream:
        msg = stream.get_final_message()
    trace.model_call(MODEL, purpose, msg.usage)
    text = "".join(b.text for b in msg.content if b.type == "text")
    if msg.stop_reason == "max_tokens" and "```json" in text and "```" not in text.split("```json", 1)[1]:
        raise ValueError("answer cut off at max_tokens")
    m = re.search(r"```json\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw), text


def local_problems(wf):
    """Cheap checks before the platform's dry run."""
    out = []
    nodes = wf.get("nodes") or {}
    if wf.get("initial_node") not in nodes:
        out.append("initial_node is not a node key")
    dumped = json.dumps(wf)
    if ": null" in dumped or ":null" in dumped:
        out.append("the workflow contains null values; remove them or use empty strings")
    for k, n in nodes.items():
        t = n.get("node_type")
        if t == "conversation" and n.get("pre_actions"):
            out.append(f"node {k}: pre_actions on a conversation node")
        if t in ("api_request", "code") and n.get("tools"):
            out.append(f"node {k}: tools on a {t} node")
        if n.get("passthrough") and not any((tr.get("condition") or {}).get("operator") == "always" for tr in n.get("transitions") or []):
            out.append(f"node {k}: passthrough node without an always transition")
        for tr in n.get("transitions") or []:
            if tr.get("target_node") not in nodes and tr.get("target_node") != "__previous__":
                out.append(f"node {k}: transition to unknown node {tr.get('target_node')}")
        for pa in (n.get("pre_actions") or []) + (n.get("tools") or []):
            code = (((pa.get("function") or {}).get("parameters") or {}).get("properties") or {}).get("code", {}).get("default", "")
            if code and ("{{" in code or "}}" in code):
                out.append(f"node {k}: code contains a double brace")
            for hook in ("pre_process_code", "post_process_code"):
                if pa.get(hook) and ("{{" in pa[hook] or "}}" in pa[hook]):
                    out.append(f"node {k}: {hook} contains a double brace")
    return out


def write_workflow(docs, mock_url, trace, validate):
    """docs: [(name, text)]. validate(wf) -> error text or "" (the platform dry run). Returns the workflow."""
    platform = "\n\n".join((KIT / "docs" / f).read_text() for f in ("workflow-format.md", "tools-and-code.md"))
    example = (KIT / "examples" / "base-agent.json").read_text()
    case = "\n\n".join(f"<document name=\"{n}\">\n{t}\n</document>" for n, t in docs)
    system = ("You are the builder of a Freya phone agent. You read a client's case documents and write the complete Freya workflow JSON "
              "for the phone agent they describe. The documents were written at different times and may disagree: the newest decision wins "
              "(later mails, later document versions, meeting decisions). Every rule in the documents must be implemented exactly.")
    base = [{"type": "text", "text": f"<platform_reference>\n{platform}\n</platform_reference>\n\n<example_workflow>\n{example}\n</example_workflow>\n\n{RULES}",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"<case>\n{case}\n</case>", "cache_control": {"type": "ephemeral"}}]
    ask = (f"The bank's services are served at this base URL (use it for every tool URL; paths and field names exactly as in the integration document): {mock_url}\n"
           "First think through the call flow, every rule, every service, and every exact sentence the documents require. "
           "Keep your planning compact: the workflow JSON is the deliverable and must fit in the answer. "
           "Then output the complete workflow JSON in one ```json block.")
    wf, _ = _ask(trace, "write the workflow from the case documents", system, base + [{"type": "text", "text": ask}], effort="medium")
    for attempt in range(4):
        problems = local_problems(wf)
        err = "" if problems else validate(wf)
        trace.event("workflow_check", attempt=attempt, local=problems, platform=(err or "")[:600])
        if not problems and not err:
            return wf
        fix = ("Here is the workflow you wrote:\n```json\n" + json.dumps(wf) + "\n```\n\nIt has these problems:\n- " +
               "\n- ".join(problems or [err[:3000]]) + "\n\nFix them and output the complete corrected workflow JSON in one ```json block.")
        wf, _ = _ask(trace, "repair the workflow after validation", system, base + [{"type": "text", "text": fix}], effort="medium")
    return wf
