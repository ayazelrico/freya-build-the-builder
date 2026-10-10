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


ROLES = {"promise", "paid", "transferred", "refused", "hardship", "dispute", "service_error", "id_failed", "id_declined",
         "callback", "no_callback", "wrong_number", "deceased", "unclear", "other"}
NEEDED_LINES = ["opening", "confirm_identity", "identity_intro", "identity_failed", "debt_intro", "first_ask", "confirm_question",
                "promise_recorded", "full_offer", "floor_offer", "goodbye"]


def problems(spec, openapi):
    """Mechanical checks of a SPEC. Returns a list of plain-language problems (empty when fine)."""
    out = []
    cv = set(spec.get("call_variables") or [])
    L = spec.get("lines") or {}
    for k in NEEDED_LINES:
        if not L.get(k):
            out.append(f"lines.{k} is missing or empty")
    for k, v in L.items():
        allowed = cv | ({"amount", "date", "floor_name"} if k in ("full_offer", "floor_offer") else set())
        for ph in re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", str(v)):
            if ph not in allowed:
                out.append(f"lines.{k} uses the placeholder {{{ph}}}, which is not allowed there (allowed: {sorted(allowed)})")
    rows = spec.get("outcomes") or []
    if not rows:
        out.append("outcomes is empty")
    seen = {}
    for r in rows:
        if r.get("role") not in ROLES:
            out.append(f"outcome row {r.get('outcome')}/{r.get('reason')} has no valid role")
        elif r["role"] != "transferred":
            seen.setdefault(r["role"], []).append(r)
    for rl, rs in seen.items():
        if len(rs) > 1 and rl != "other":
            out.append(f"role {rl} is used by {len(rs)} rows")
    if "promise" not in seen:
        out.append("no outcome row has role promise")
    paths = (openapi.get("paths") or {})
    vi = ((paths.get("/verify_identity") or {}).get("post") or {})
    enum = []
    try:
        enum = vi["requestBody"]["content"]["application/json"]["schema"]["properties"][(spec.get("identity") or {}).get("field_param") or "field"].get("enum") or []
    except Exception:
        pass
    for q in (spec.get("identity") or {}).get("questions") or []:
        if enum and q.get("field") not in enum:
            out.append(f"identity question field {q.get('field')} is not one of the tool API values {enum}")
    for b in spec.get("bands") or []:
        if (b.get("deadline") or {}).get("type") not in ("business_days_after_today", "business_days_after_today_counting_today", "calendar_days_after_today", "end_of_month", "end_of_next_month", "fixed_date"):
            out.append(f"band {b.get('name')} has an unknown deadline type")
    for h in (spec.get("calendar") or {}).get("holidays") or []:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(h)):
            out.append(f"holiday {h} is not YYYY-MM-DD")
    return out


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
    except (json.JSONDecodeError, ValueError, anthropic.APIError) as e:
        trace.event("review_failed_keeping_first_spec", error=str(e)[:200])
    openapi = json.loads(openapi_text)
    for attempt in range(2):
        found = problems(spec, openapi)
        trace.event("spec_check", attempt=attempt, problems=found)
        if not found:
            break
        fix = (base + "Here is a SPEC written for these briefs:\n```json\n" + json.dumps(spec, indent=1) + "\n```\n\n"
               "An automatic check found these problems:\n- " + "\n- ".join(found) + "\n\nFix them and return the whole corrected SPEC.")
        try:
            spec = _ask(trace, "repair the SPEC after the automatic check", fix, effort="medium")
        except (json.JSONDecodeError, ValueError, anthropic.APIError) as e:
            trace.event("repair_failed_keeping_spec", error=str(e)[:200])
            break
    return spec
