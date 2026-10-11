"""SPEC + openapi.json -> Freya workflow JSON. Deterministic: the same inputs give the same workflow.

The spec holds everything taken from the brief (see builder/spec_schema.md). Nothing in this file
knows a particular brief: tool fields come from the openapi file, rules and values from the spec.
"""
import json, os, re

from . import runtime_code as rc

NO_TOOL_TEXT = ""


# ---------------------------------------------------------------- tools from openapi
def load_tools(openapi):
    """{tool_name: {url, fields: {name: schema}, required: [...]}} from the openapi file."""
    server = (openapi.get("servers") or [{}])[0].get("url", "").rstrip("/")
    out = {}
    for path, ops in (openapi.get("paths") or {}).items():
        op = ops.get("post") or ops.get("put") or next(iter(ops.values()))
        name = path.strip("/").split("/")[-1]
        schema = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
        resp = (((op.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json", {}).get("schema", {})
        out[name] = {"url": server + path, "method": "POST" if "post" in ops else "PUT", "summary": op.get("summary", ""),
                     "fields": schema.get("properties") or {}, "required": schema.get("required") or [],
                     "response": resp.get("properties") or {}}
    return out


def api_tool(tools, name, description, call_vars, baked=None, model_names=None, config=None, pre=None, post=None, mapping=None):
    """An api_call tool. Fields named like a call variable are baked from it, `baked` overrides,
    the rest are filled by the model (default "{{<model name>}}" where no variable of that name exists)."""
    t = tools[name]
    props = {}
    for f, sch in t["fields"].items():
        leaf = {"type": sch.get("type", "string")}
        if sch.get("type") == "number":
            leaf["type"] = "number"
        desc = sch.get("description", "")
        if sch.get("enum"):
            leaf["enum"] = sch["enum"]
            desc = (desc + " One of: " + ", ".join(sch["enum"]) + ".").strip()
        if sch.get("format") == "date":
            desc = (desc + " Date as YYYY-MM-DD.").strip()
        if baked and f in baked:
            leaf["default"] = baked[f]
        elif f in call_vars:
            leaf["default"] = "{{" + f + "}}"
        else:
            leaf["default"] = "{{" + (model_names or {}).get(f, f) + "}}"
        if desc:
            leaf["description"] = desc
        props[f] = leaf
    tool = {
        "type": "function",
        "config": config or {"timeoutMs": 12000, "maxRetries": 0},
        "function": {
            "name": name,
            "handler": "__function__:api_call",
            "description": description,
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "default": t["url"]},
                "method": {"type": "string", "default": t["method"]},
                "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                "body": {"type": "object", "properties": props, "required": [f for f in t["required"] if f in props]},
            }},
        },
    }
    if pre: tool["pre_process_code"] = pre
    if post: tool["post_process_code"] = post
    if mapping: tool["response_mapping"] = mapping
    return tool


# ---------------------------------------------------------------- helpers
def cond_eq(var, *vals):
    return {"logic": "or", "conditions": [{"variable": var, "operator": "equals", "operand": v} for v in vals]}


def cond_true(var):
    return cond_eq(var, "true", "True")


def cond_and(*conds):
    return {"logic": "or", "conditions": [{"logic": "and", "conditions": list(conds)}]}


def always(target):
    return {"target_node": target, "description": "always", "condition": {"operator": "always"}}


def no_recorded(s):
    """'recorded' before a promise is saved reads as a false claim. Rephrase a recording notice."""
    s = re.sub(r"(?i)\b(this|the) call (is|will be|is being|may be) recorded\b", "we record this call", s or "")
    return re.sub(r"(?i)(^|[.!?]\s+)we record", lambda m: m.group(1) + "We record", s)


def tmpl(s):
    """Spec text uses {var} for call variables. Turn it into the platform's {{var}}."""
    return re.sub(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})", r"{{\1}}", s or "")


ROLES = ("promise", "paid", "transferred", "refused", "hardship", "dispute", "service_error", "id_failed", "id_declined",
         "callback", "no_callback", "wrong_number", "deceased", "unclear", "other")


def role(row):
    return row.get("role") or "other"


def end_key(outcome, reason):
    return "end_" + re.sub(r"\W+", "_", outcome + ("_" + reason if reason else "")).strip("_").lower()


def code_node(name, code, target, extra_transitions=None):
    return {
        "name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": target,
        "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
        "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                         "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code},
                                                                         "timeout_ms": {"type": "number", "default": 15000}}}}}],
        "transitions": (extra_transitions or []) + [always(target)],
    }


def conv_node(name, task, tools=None, transitions=None, on_enter=None, extraction=None, max_turns=40, max_target=None, first_only=True):
    n = {
        "name": name, "node_type": "conversation", "task_message": task, "role_message": "",
        "tools": tools or [], "transitions": transitions or [], "extraction_schema": extraction or [],
        "on_enter": on_enter or {"type": "llm"}, "on_enter_first_entry_only": first_only,
        "max_node_turns": max_turns, "truncation_strategy": "keep_all", "interruptible": os.environ.get("NODE_INTERRUPTIBLE", "0") == "1",
    }
    if max_target:
        n["max_turn_transition"] = max_target
    return n


def end_transition(spec, row, when=None):
    key = end_key(row["outcome"], row.get("reason") or "")
    label = row["outcome"] + (" / " + row["reason"] if row.get("reason") else "")
    desc = "End the call as " + label + ". CALL this when: " + (when or row.get("when", "")) + ". Say nothing else after calling it; the closing words are spoken automatically."
    return {"target_node": key, "description": desc, "is_tool_call": True,
            "condition": {"operator": "matches_intent", "description": desc}}


# ---------------------------------------------------------------- the workflow
def build(spec, openapi):
    tools = load_tools(openapi)
    call_vars = set(spec.get("call_variables") or ["customer_id"])
    L = spec.get("lines") or {}
    R = spec.get("rules_text") or {}
    I = spec.get("identity") or {}
    T = spec.get("transfer") or {}
    P = spec.get("promise_tool") or {}
    C = spec.get("close") or {}
    notes = spec.get("notes") or {}
    data = {k: spec.get(k) for k in ("calendar", "callback", "identity", "account", "product_types", "bands", "attempts",
                                      "promise_tool", "transfer", "notes", "lines", "currency_word", "close", "outcomes")}
    have = set(tools)
    if "schedule_callback" in tools:     # which callback fields hold the date and the time, from the tool API
        cf = tools["schedule_callback"]["fields"]
        dp = [f for f, x in cf.items() if x.get("format") == "date" or "date" in f or "day" in f]
        tp = [f for f, x in cf.items() if f not in dp and ("time" in f or "hour" in f or "HH" in str(x.get("description", "")))]
        data["callback"] = dict(data.get("callback") or {}, date_param=dp[0] if dp else "date", time_param=tp[0] if tp else "time")

    def key_for(rl):
        rows = [r for r in spec.get("outcomes") or [] if role(r) == rl]
        return end_key(rows[0]["outcome"], rows[0].get("reason") or "") if rows else None

    def stage_rows(*stages):
        return [r for r in spec.get("outcomes") or [] if r.get("stage") in stages + ("any",)]

    # -------- tools
    qparam = T.get("queue_param") or "queue"
    transfer = api_tool(tools, "transfer_to_agent",
                        "Hand the call to a person. CALL it only when the rules say to transfer: give the queue the rules name.",
                        call_vars, pre=rc.fill(rc.TRANSFER_PRE, data, QPARAM=rc.pystr(qparam)), post=rc.fill(rc.TRANSFER_POST, data)) if "transfer_to_agent" in have else None
    verify = api_tool(tools, "verify_identity",
                      "Check ONE security answer. CALL it every time the customer gives an answer to a security question, with the field of the question you asked and the answer as the customer gave it.",
                      call_vars, pre=rc.fill(rc.VERIFY_PRE, data), post=rc.fill(rc.VERIFY_POST, data))
    callback = api_tool(tools, "schedule_callback",
                        "Book a callback for the customer. CALL it as soon as the person names a day and time inside the allowed window. Date as YYYY-MM-DD, time as HH:MM (24 hour).",
                        call_vars, pre=rc.fill(rc.CALLBACK_PRE, data), post=rc.fill(rc.CALLBACK_POST, data)) if "schedule_callback" in have else None
    promise = api_tool(tools, "create_promise",
                       "Record ONE payment promise for ONE product. CALL it only after the customer said yes to your read-back. product_id from the facts, amount as a number, date as YYYY-MM-DD.",
                       call_vars, pre=rc.fill(rc.PROMISE_PRE, data), post=rc.fill(rc.PROMISE_POST, data))
    note = None
    if notes.get("enabled") and "add_note" in have:
        note = api_tool(tools, notes.get("tool") or "add_note",
                        "Record why ONE product ended without a promise. CALL it once for each product without a promise, with its product_id and the reason.",
                        call_vars, pre=rc.fill(rc.NOTE_PRE, data, PPARAM=rc.pystr(notes.get("product_param") or "product_id"), RPARAM=rc.pystr(notes.get("reason_param") or "reason")),
                        post=rc.fill(rc.NOTE_POST, data))
        # the transcript reaches the pre-hook through a header; the hook removes it before the request is sent
        note["function"]["parameters"]["properties"]["headers"]["properties"]["X-Conversation"] = {"type": "string", "default": "{{system.conversation}}"}

    close_tool = api_tool(tools, "close_call", "Record how the call ended.", call_vars,
                          baked={C.get("outcome_param") or "outcome": "{{close_outcome}}", C.get("reason_param") or "reason": "{{close_reason}}"},
                          config={"timeoutMs": 12000, "maxRetries": 1, "alwaysRunsAt": ["end_of_call"]},
                          pre=rc.fill(rc.CLOSE_PRE, data, OPARAM=rc.pystr(C.get("outcome_param") or "outcome"),
                                      RPARAM=rc.pystr(C.get("reason_param") or "reason"), NOREASON=rc.embed(C.get("no_reason_outcomes") or sorted({r["outcome"] for r in spec.get("outcomes") or [] if not r.get("reason")}))))
    # close_call is never a dialogue tool: the end code nodes set close_outcome / close_reason.
    close_tool["function"]["description"] = "Record how the call ended. Outcome and reason come from the conversation and the brief's outcome table."

    # -------- shared prompt parts
    bank = spec.get("bank_name") or "the bank"
    lang = spec.get("language") or "English"
    system = (
        f"You are the digital assistant of {bank}, on a phone call. Speak {lang} only. Keep every turn to one or two short sentences. "
        "Say amounts as numbers and dates as weekday plus day and month. Never invent facts, figures, dates or reasons.\n"
        "Tool results may contain 'what_to_do_next'. Always do exactly what it says. After every tool result, speak to the customer or call the next tool; never end a turn with nothing.\n"
        "Call at most one tool per message. When a rule says to call a tool, call it; saying you did is not enough. "
        "A transfer is always a tool call on its own: never call another tool in the same message as transfer_to_agent, and never write notes when you transfer.\n"
        "Never say goodbye yourself: to end the call, call the matching end tool and the closing words are spoken for you.\n"
        "Customers talk like people. If they give a number or a date in parts, wait for the rest and use the whole value: the parts go together in the order the customer said them "
        "(first part first). Ask 'And the rest?', never for 'the first digits'. A bare number like 'twenty' may be the start of 'twenty-sixth' or 'twenty-five', so wait for the rest. "
        "If they correct themselves ('the 21st, sorry, the 20th'), use only the corrected value. Amounts and dates said in words count like digits. "
        "If they ask a question back or talk about something else, answer briefly and return to your question. "
        "A date they mention that is not about paying (a wedding, a birthday) is not a payment date.\n"
        "If the customer's message is cut off mid-sentence, it is not an answer: reply only 'I'm listening.' Do not repeat a question or an offer then, because every repeat counts as asking or offering again. "
        "If a complete message is only small talk, acknowledge it in at most three words and ask your current question once more. "
        "A cut-off or off-topic message is never a refusal, a decline or a non-answer, and never uses up an attempt or an ask.\n"
        "Only an explicit no ('no', 'I will not', 'I don't want to') counts as a refusal or a decline.\n"
        "Never repeat an offer, a question or a proposal the customer has already answered; if they answered it, move on.\n\n"
        "RULES THAT ALWAYS APPLY:\n" + (R.get("global") or "")
    )
    pre_verif = ("\nBefore identity is verified you must not say any of these: " + ", ".join(spec.get("forbidden_before_verification") or []) + ". Do not say why you are calling.") if spec.get("forbidden_before_verification") else ""

    nodes = {}

    # -------- setup
    nodes["setup"] = code_node("setup", rc.fill(rc.SETUP, data), "opening")

    # -------- opening: who is on the line
    contact_ends = [end_transition(spec, r) for r in stage_rows("contact") if role(r) not in ("transferred", "unclear")]
    third_rows = stage_rows("third_party")
    opening_tr = [
        {"target_node": "identity", "is_tool_call": True,
         "description": "CALL as soon as the person confirms they are {{first_name}} {{last_name}} ({{title}} {{last_name}}).",
         "condition": {"operator": "matches_intent", "description": "The person confirmed they are {{title}} {{last_name}}."}},
    ]
    if third_rows and callback:
        opening_tr.append({"target_node": "third_party", "is_tool_call": True,
                           "description": "CALL when the person says they are NOT {{first_name}} {{last_name}} but someone else who knows them (a relative, partner, colleague, flatmate).",
                           "condition": {"operator": "matches_intent", "description": "Someone other than the customer answered."}})
    opening_tr += contact_ends
    opening_tools = [t for t in [transfer] if t]
    if transfer:
        opening_tr = [transfer_route(spec, q) for q in (T.get("queue_to_reason") or {})] + opening_tr
    c = spec.get("contact") or {}
    nodes["opening"] = conv_node(
        "opening",
        "You have just said the opening line and asked whether you are speaking with {{title}} {{last_name}}. "
        "Your only job now is to find out who is on the line.\n" + (R.get("contact") or "") + pre_verif +
        "\nThe customer's full name: {{first_name}} {{last_name}}. Address them as {{title}} {{last_name}}.",
        tools=opening_tools, transitions=opening_tr,
        on_enter={"type": "tts", "text": tmpl(no_recorded(L.get("opening") or "") + " " + (L.get("confirm_identity") or "Am I speaking with {title} {last_name}?"))},
        max_turns=14, max_target=key_for("unclear"))

    # -------- third party
    if third_rows and callback:
        tp_tr = [{"target_node": key_for("callback"), "description": "callback scheduled",
                  "condition": cond_eq("callback_state", "scheduled")}] if key_for("callback") else []
        tp_tr += [end_transition(spec, r) for r in third_rows + stage_rows("contact") if role(r) not in ("callback", "unclear", "transferred")]
        nodes["third_party"] = conv_node(
            "third_party",
            "The person on the line is NOT the customer {{first_name}} {{last_name}}. Do not say why you are calling. Ask when {{title}} {{last_name}} can be reached.\n"
            "{{callback_facts}}\n" + (R.get("third_party") or "") + pre_verif +
            "\nWhen the person names a day and time, call schedule_callback with the date (YYYY-MM-DD) and time (HH:MM).",
            tools=[callback], transitions=tp_tr, max_turns=20)

    # -------- identity
    qs = I.get("questions") or []
    id_rows = stage_rows("identity")
    id_tr = [{"target_node": "load_account", "description": "identity verified",
              "condition": {"logic": "or", "conditions": [
                  {"variable": "identity_state", "operator": "equals", "operand": "verified"},
                  {"variable": "verify_identity_response.data." + ((I.get("response") or {}).get("all_ok") or "all_verified"), "operator": "equals", "operand": "true"},
                  {"variable": "verify_identity_response.data." + ((I.get("response") or {}).get("all_ok") or "all_verified"), "operator": "equals", "operand": "True"}]}}]
    if key_for("id_failed"):
        id_tr.append({"target_node": key_for("id_failed"), "description": "identity check failed",
                      "condition": {"logic": "or", "conditions": [
                          {"variable": "identity_state", "operator": "equals", "operand": "failed"},
                          {"variable": "verify_identity_response.data." + ((I.get("response") or {}).get("remaining") or "wrong_answers_left"), "operator": "equals", "operand": "0"}]}})
    if transfer:
        id_tr = [transfer_route(spec, q) for q in (T.get("queue_to_reason") or {})] + id_tr
    id_tr += [end_transition(spec, r) for r in id_rows if role(r) not in ("id_failed", "transferred")]
    q_text = "\n".join(f"{i + 1}. field '{q['field']}': ask \"{q['ask']}\"" + (f" ({q.get('answer_format')})" if q.get("answer_format") else "") for i, q in enumerate(qs))
    nodes["identity"] = conv_node(
        "identity",
        "The customer confirmed who they are. Now verify identity. Ask the security questions one at a time, in this order:\n" + q_text +
        "\nAfter every answer CALL verify_identity with that question's field and the answer exactly as the customer gave it (a date of birth may be sent in any form; it is converted for you). "
        "Then follow what_to_do_next from the result. Never tell the customer an answer is right or wrong before the tool result. "
        "If an answer is clearly incomplete (a date without the year, fewer digits than asked), ask for the missing part first and call verify_identity once with the complete answer. "
        "As soon as the answer is complete (also when it came in several messages, or together with a question or a complaint), call verify_identity right away, before you say anything else; deal with the question afterwards.\n" +
        (R.get("identity") or "") + pre_verif,
        tools=[verify] + ([transfer] if transfer else []), transitions=id_tr,
        on_enter={"type": "tts", "text": tmpl((L.get("identity_intro") or "") + " " + (qs[0]["ask"] if qs else ""))},
        max_turns=40, max_target=key_for("id_declined"))

    # -------- account
    acc = spec.get("account") or {}
    get_acc_props = {f: {"type": "string", "default": "{{" + f + "}}"} for f in tools["get_account"]["fields"] if f in call_vars}
    nodes["load_account"] = {
        "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "compute",
        "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
        "pre_actions": [{"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 2}, "function": {
            "name": "get_account", "handler": "__function__:api_call", "description": "Get the late products.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "default": tools["get_account"]["url"]},
                "method": {"type": "string", "default": "POST"},
                "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                "body": {"type": "object", "properties": get_acc_props, "required": []}}}}}],
        "response_mapping": [{"path": "data." + (acc.get("products_field") or "products"), "variable": "account_products"}],
        "transitions": [always("compute")],
    }
    nodes["compute"] = code_node("compute", rc.fill(rc.COMPUTE, data), "negotiate")

    # -------- negotiate
    neg_rows = stage_rows("negotiate")
    neg_tr = []
    if transfer:
        neg_tr += [transfer_route(spec, q) for q in (T.get("queue_to_reason") or {})]
    if key_for("promise"):   # its own node, so the engine does not merge it with the model's end tool for the same row
        neg_tr.append({"target_node": "end_all_promised", "description": "every product has a recorded promise",
                       "condition": cond_eq("promises_all", "yes")})
    ends = [r for r in neg_rows if role(r) != "transferred"]
    neg_tr += [end_transition(spec, r) for r in ends]
    check_tool = {"type": "function", "config": {"timeoutMs": 10000}, "function": {
        "name": "check_payment", "handler": "__function__:code_exec",
        "description": "Check a payment day and/or amount against the bank's rules. CALL it every time the customer names a day or an amount, "
                       "BEFORE you answer them, then say what its what_to_do_next says.",
        "parameters": {"type": "object", "properties": {
            "day": {"type": "string", "description": "The payment day exactly in the customer's words, all pieces joined in the order they were said (e.g. 'Monday the twenty sixth', 'next Friday', 'tomorrow'). Empty if none."},
            "amount": {"type": "string", "description": "The amount the customer proposed, as a number. Empty if none."},
            "product": {"type": "string", "description": "Which product it is for (product_id from the facts). Empty for all products."},
            "code": {"type": "string", "default": rc.fill(rc.CHECK_PAYMENT, data)}},
            "required": []}}}
    neg_tools = [check_tool, promise] + ([note] if note else []) + ([transfer] if transfer else [])
    multi_text = ""
    if spec.get("multi_product"):
        multi_text = ("\nSEVERAL PRODUCTS: the facts list them in order. Follow the multi-product rules below. "
                      "Persuasion attempts are counted per product. Read all agreed promises back together and ask for one confirmation, then call create_promise once per product, one after the other.")
    note_text = ""
    if note:
        note_text = f"\nFor every product that ends without a promise, call {note['function']['name']} with its product_id and the reason (one of: " + ", ".join(notes.get("reasons") or []) + ") before ending the call."
    nodes["negotiate"] = conv_node(
        "negotiate",
        "The customer is verified. You have just stated the debt and asked the first question. Now get a payment promise under the rules.\n\n"
        "FACTS (computed by the bank; trust them over your own date arithmetic):\n{{negotiation_facts}}\n\n"
        "RULES:\n" + (R.get("negotiate") or "") + multi_text + note_text +
        "\n\nDATES AND AMOUNTS: whenever the customer names a payment day or an amount, CALL check_payment first (day in their own words, amount, product) and answer with what its what_to_do_next says. "
        "Never judge a day or an amount yourself; DATE LOOKUP in the facts is only a backup if the tool fails.\n"
        "OFFERS: for a refusal or a non-answer use the product's OFFER SEQUENCE, in order, each offer once. Ask whether they can pay today only once in the whole call.\n"
        "SPECIAL SITUATIONS FIRST: as soon as the customer mentions a situation the rules handle specially (hardship such as illness, job loss or a death; a dispute; already paid; "
        "a request for a new plan or a person), apply that rule at once. It takes priority over the offer sequence: make no further offers unless the rule allows them.\n"
        "AMOUNTS: unless the rules say otherwise, never ask how much the customer can or will pay. If they name a day but no amount, propose the full amount for that day.\n"
        "HONESTY: before create_promise returns ok, never say a promise is recorded, saved, booked, noted or set up. While agreeing, say you will read everything back for confirmation.\n"
        "Before create_promise: read back the product, the amount and the date (weekday, day and month) and ask " + json.dumps(L.get("confirm_question") or "Do you confirm?") + ". Call create_promise only after a clear yes.\n"
        "When the call should end, call the matching end tool. Do not end after a recorded promise yourself; that happens automatically.",
        tools=neg_tools, transitions=neg_tr,
        on_enter={"type": "tts", "text": "{{debt_statement}}"},
        max_turns=90, max_target=key_for("refused"))

    # -------- ends
    for r in spec.get("outcomes") or []:
        key = end_key(r["outcome"], r.get("reason") or "")
        if key in nodes:
            continue
        code = rc.fill(rc.END_PATH, {}, OUTCOME=rc.pystr(r["outcome"]), REASON=rc.pystr(r.get("reason") or ""), ROLE=rc.pystr(role(r)))
        nodes[key] = code_node(key, code, "finalize")
    pr = [r for r in spec.get("outcomes") or [] if role(r) == "promise"]
    if pr:
        nodes["end_all_promised"] = code_node("end_all_promised", rc.fill(rc.END_PATH, {}, OUTCOME=rc.pystr(pr[0]["outcome"]),
                                              REASON=rc.pystr(pr[0].get("reason") or ""), ROLE=rc.pystr("promise")), "finalize")
    nodes["finalize"] = code_node("finalize", rc.fill(rc.END, data), "goodbye")
    nodes["goodbye"] = {
        "name": "goodbye", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
        "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call", "parameters": {"type": "object", "properties": {
            "message_mode": {"type": "string", "default": "custom"},
            "spoken_message": {"type": "string", "default": "{{farewell_text}}"}}}}},
    }

    # drop transitions to nodes that do not exist (an outcome the spec lacks)
    for n in nodes.values():
        n["transitions"] = [t for t in n.get("transitions", []) if t["target_node"] in nodes]
        if n.get("max_turn_transition") and n["max_turn_transition"] not in nodes:
            n.pop("max_turn_transition")

    wf = {
        "initial_node": "setup",
        "system_prompt": system,
        "nodes": nodes,
        "global_nodes": {},
        "tools": [close_tool],
        "test_variables": {"customer_id": "c_test", "first_name": "Alex", "last_name": "Morgan", "title": "Mr", "now": "2026-10-14T11:00"},
    }
    return wf


def transfer_route(spec, queue):
    reason = ((spec.get("transfer") or {}).get("queue_to_reason") or {}).get(queue, queue)
    rows = [r for r in spec.get("outcomes") or [] if role(r) == "transferred"]
    match = [r for r in rows if (r.get("reason") or "") == reason] or rows
    target = end_key(match[0]["outcome"], match[0].get("reason") or "") if match else "finalize"
    return {"target_node": target, "description": f"transfer to {queue} done",
            "condition": cond_eq("transfer_done_queue", queue)}
