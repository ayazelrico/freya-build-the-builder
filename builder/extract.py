"""Brief(s) + tool API -> SPEC, with Claude. Two passes: extract, then a coverage review that fixes the SPEC."""
import json, os, pathlib, re

import anthropic

HERE = pathlib.Path(__file__).resolve().parent
MODEL = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")

SYSTEM = (
    "You convert a bank's collections brief into a machine-readable SPEC for a phone-agent generator. "
    "Precision matters more than anything: every number, date, limit, enum value and required sentence must match the brief exactly. "
    "Read raw material carefully: when a memo, mail or later note changes a rule, only the changed rule counts. "
    "Answer with a single JSON object in a ```json block and nothing else."
)


def _client():
    return anthropic.Anthropic(max_retries=4)


def _ask(trace, purpose, prompt, effort="high"):
    with _client().messages.stream(
        model=MODEL, max_tokens=64000, system=SYSTEM,
        thinking={"type": "adaptive"}, output_config={"effort": effort},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if b.type == "text")
    trace.model_call(MODEL, purpose, msg.usage)
    m = re.search(r"```json\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def extract_spec(brief_texts, openapi_text, trace):
    schema = (HERE / "spec_schema.md").read_text()
    briefs = "\n\n".join(f"<brief file=\"{name}\">\n{text}\n</brief>" for name, text in brief_texts)
    base = f"{schema}\n\n<tool_api>\n{openapi_text}\n</tool_api>\n\n{briefs}\n\n"
    if len(brief_texts) > 1:
        base += "The later briefs build on the earlier ones: every earlier rule applies unless a later one replaces it.\n\n"
    try:
        spec = _ask(trace, "extract the SPEC from the brief", base + "Write the SPEC for these briefs.")
    except (json.JSONDecodeError, ValueError):
        spec = _ask(trace, "extract the SPEC (retry after invalid JSON)", base + "Write the SPEC for these briefs. Output valid JSON only.")
    review = (
        base + "Here is a SPEC written for these briefs:\n```json\n" + json.dumps(spec, indent=1) + "\n```\n\n"
        "Review it against the briefs line by line. Check: every rule of the brief is represented (in a field or in rules_text); "
        "every value is exact; rules changed by later material use the changed version; every outcome row is present with a correct stage; "
        "tool parameter and field names match the tool API exactly; required sentences are in `lines`. "
        "Return the corrected, complete SPEC (the whole object)."
    )
    try:
        spec = _ask(trace, "coverage review and correction of the SPEC", review)
    except (json.JSONDecodeError, ValueError):
        pass
    return spec
