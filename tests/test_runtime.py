"""Run the workflow's code nodes and hooks locally on the practice cases. No network."""
import json, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder import generate

def node_code(wf, name):
    return wf["nodes"][name]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]

def tool(wf, node, name):
    return [t for t in wf["nodes"][node]["tools"] if t["function"]["name"] == name][0]

def run(code, vars, **extra):
    g = {"vars": vars, **extra}
    exec(code, g)
    return g

def main(spec_path, openapi_path, cases_path, brief):
    spec = json.load(open(spec_path)); wf = generate.build(spec, json.load(open(openapi_path)))
    print("workflow size", len(json.dumps(wf)))
    for c in json.load(open(cases_path)):
        if c["brief"] not in brief: continue
        v = dict(c["variables"], customer_id="c_x")
        run(node_code(wf, "setup"), v)
        prods = [dict(p, product_id=f"p{i+1}") for i, p in enumerate(c["products"])]
        for i, p in enumerate(prods):   # the platform stores a pre_actions result flattened under <node>_response
            for k, x in p.items(): v[f"load_account_response.data.products.{i}.{k}"] = x
        run(node_code(wf, "compute"), v)
        print("=" * 80, c["id"], c["title"]); print(v.get("callback_facts")); print(v["debt_statement"])
        exp = c["expected"]["promises"]
        P = json.loads(v["products_json"])
        print([(p["product_id"], p["band"], p["deadline"], p["floor"], [a["date"] for a in p["plan"]]) for p in P])
        for e in exp:   # the expected promise must pass our own pre-hook
            cfg = {"body": {"customer_id": "c_x", "product_id": e["product_id"], "amount": e["amount"], "date": e["date"]}}
            run(tool(wf, "negotiate", "create_promise")["pre_process_code"], v, config=cfg)
            assert not v.get("promise_block"), (c["id"], v["promise_block"])
        if c["id"] == "PUB-07":
            cfg = {"body": {"customer_id": "c_x", "product_id": "p1", "amount": 540, "date": "26 October 2026"}}
            run(tool(wf, "negotiate", "create_promise")["pre_process_code"], v, config=cfg); print("26 Oct ->", v["promise_block"])
        if c["id"] == "PUB-04":
            cfg = {"body": {"customer_id": "c_x", "product_id": "p1", "amount": 1250, "date": "2026-11-06"}}
            run(tool(wf, "negotiate", "create_promise")["pre_process_code"], v, config=cfg); print("6 Nov ->", v["promise_block"])
            res = {"status": "success", "data": {"ok": False, "error": "unknown customer"}, "header": {}}
            run(tool(wf, "negotiate", "create_promise")["post_process_code"], v, result=res); print(res["data"]["what_to_do_next"])
        if c["id"] == "PUB-02":
            cfg = {"body": {"customer_id": "c_x", "date": "2026-10-15", "time": "11am"}}
            run(tool(wf, "third_party", "schedule_callback")["pre_process_code"], v, config=cfg); print("callback", cfg["body"], repr(v["callback_block"]))
            cfg = {"body": {"customer_id": "c_x", "date": "2026-10-15", "time": "20:00"}}
            run(tool(wf, "third_party", "schedule_callback")["pre_process_code"], v, config=cfg); print("callback 20:00", repr(v["callback_block"]))
        if c["id"] == "PUB-03":
            vt = tool(wf, "identity", "verify_identity")
            for ans in ["12 July 1991", "21/08/1992", "July 21st, 1990"]:
                cfg = {"body": {"customer_id": "c_x", "field": "date_of_birth", "answer": ans}}
                run(vt["pre_process_code"], v, config=cfg); print("dob", ans, "->", cfg["body"]["answer"])
            res = {"status": "success", "data": {"ok": True, "verified": False, "wrong_answers_left": 1, "all_verified": False}, "header": {}}
            run(vt["post_process_code"], v, result=res); print(res["data"]["what_to_do_next"])
            res = {"status": "success", "data": {"ok": True, "verified": True, "wrong_answers_left": 2, "all_verified": False}, "header": {}}
            run(vt["post_process_code"], v, result=res); print(res["data"]["what_to_do_next"])
        # finalize for the expected outcome path
        rw = [r for r in spec["outcomes"] if r["outcome"] == c["expected"]["outcome"] and (r.get("reason") or "") == (c["expected"]["reason"] or "")][0]
        v2 = dict(v, end_path_outcome=rw["outcome"], end_path_reason=rw.get("reason") or "", end_path_role=rw.get("role", "other"))
        if exp: v2["promises_recorded"] = str(len(exp))
        run(node_code(wf, "finalize"), v2); print("close:", v2["close_outcome"], repr(v2["close_reason"]), "|", v2["farewell_text"])
        cfg = {"body": {"customer_id": "c_x", "outcome": v2["close_outcome"], "reason": v2["close_reason"]}}
        run(wf["tools"][0]["pre_process_code"], v2, config=cfg)
        assert ("reason" in cfg["body"]) == bool(c["expected"]["reason"]), cfg
    print("\nALL OK")

if __name__ == "__main__":
    main(*(sys.argv[1:4] or [ROOT / "fixtures/brief-a.spec.json", ROOT / "tools/openapi.json", ROOT / "public-test-set.json"]), brief=sys.argv[4] if len(sys.argv) > 4 else "AB")


def test_note_check():
    spec = json.load(open(ROOT / "fixtures/brief-ab.llm-spec.json")); wf = generate.build(spec, json.load(open(ROOT / "tools/openapi.json")))
    v = {"customer_id": "c", "first_name": "M", "last_name": "B", "title": "Mr", "now": "2026-10-14T11:00"}
    prods = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510, "days_late": 16, "minimum_payment": 153},
             {"product_id": "p2", "type": "personal_loan", "past_due": 1320, "days_late": 16, "instalment_amount": 440}]
    for i, p in enumerate(prods):
        for k, x in p.items(): v[f"load_account_response.data.products.{i}.{k}"] = x
    run(node_code(wf, "compute"), v)
    nt = tool(wf, "negotiate", "add_note")
    conv1 = "AGENT: Can you pay all of them today?\nUSER: No.\nAGENT: Can you pay the full 1320 on Friday 16 October?\nUSER: No."
    cfg = {"headers": {"X-Conversation": conv1}, "body": {"customer_id": "c", "product_id": "p2", "reason": "refused"}}
    run(nt["pre_process_code"], v, config=cfg); print("one offer only ->", v["note_block"][:160], "| header removed:", "X-Conversation" not in cfg["headers"])
    assert v["note_block"] and cfg["body"]["customer_id"] == "blocked-by-agent-policy"
    conv2 = conv1 + "\nAGENT: I can record the instalment amount of 440 on Friday 23 October; the rest stays overdue.\nUSER: No."
    cfg = {"headers": {"X-Conversation": conv2}, "body": {"customer_id": "c", "product_id": "p2", "reason": "refused"}}
    v["note_checked"] = ""
    run(nt["pre_process_code"], v, config=cfg); print("both offers ->", repr(v["note_block"]))
    assert not v["note_block"] and cfg["body"]["customer_id"] == "c"
    conv3 = repr([{"role": "assistant", "content": "Can you pay all of them today?"}, {"role": "user", "content": "No, not 1320 on Friday 23 October."}])
    cfg = {"headers": {"X-Conversation": conv3}, "body": {"customer_id": "c", "product_id": "p2", "reason": "refused"}}
    v["note_checked"] = ""
    run(nt["pre_process_code"], v, config=cfg); print("repr transcript, offers only by user ->", v["note_block"][:60])
    assert v["note_block"]
    print("NOTE CHECK OK")


test_note_check()


def run_tool(code, vars, params):
    g = {}
    exec("def _f(vars, params):\n" + "\n".join("    " + ln for ln in code.split("\n")), g)
    return g["_f"](vars, params)


def test_check_payment():
    spec = json.load(open(ROOT / "fixtures/brief-ab.llm-spec.json")); wf = generate.build(spec, json.load(open(ROOT / "tools/openapi.json")))
    code = [t for t in wf["nodes"]["negotiate"]["tools"] if t["function"]["name"] == "check_payment"][0]["function"]["parameters"]["properties"]["code"]["default"]
    v = {"customer_id": "c", "first_name": "S", "last_name": "O", "title": "Mr", "now": "2026-10-14T11:00"}   # a Wednesday
    prods = [{"product_id": "p1", "type": "personal_loan", "past_due": 540, "days_late": 5, "instalment_amount": 180},
             {"product_id": "p2", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300}]
    for i, p in enumerate(prods):
        for k, x in p.items(): v[f"load_account_response.data.products.{i}.{k}"] = x
    run(node_code(wf, "compute"), v)
    cases = [("Monday the 26th", "p1", "2026-10-26", "next business day, Tuesday 27"),
             ("the twenty-sixth", "p1", "2026-10-26", "Tuesday 27"),
             ("Monday the 25th, I mean Monday the 26th", "p1", "2026-10-26", "Tuesday 27"),
             ("next Friday", "p1", "2026-10-23", "fine"),
             ("this Friday", "p1", "2026-10-16", "fine"),
             ("Friday", "p1", "2026-10-16", "fine"),
             ("tomorrow", "p1", "2026-10-15", "fine"),
             ("6 November", "p2", "2026-11-06", "after the deadline"),
             ("the sixth of November", "p2", "2026-11-06", "Friday 23 October"),
             ("30 October", "", "2026-10-30", "after the deadline"),
             ("2026-10-27", "p1", "2026-10-27", "fine"),
             ("October 6th", "p1", "2026-10-06", "in the past"),
             ("Monday the twenty sixth", "p1", "2026-10-26", "Tuesday 27"),
             ("thirty October", "", "2026-10-30", "after the deadline"),
             ("twenty three October", "p2", "2026-10-23", "fine"),
             ("the twenty-first", "p1", "2026-10-21", "fine"),
             ("thirty first of October", "p1", "2026-10-31", "not a business day"),
             ("next week", "p1", "", "vague period"),
             ("when my salary comes", "p1", "", "vague period")]
    for words, prod, want, phrase in cases:
        r = run_tool(code, v, {"day": words, "product": prod})
        ok = r["day"] == want and phrase in r["what_to_do_next"]
        print(("ok  " if ok else "BAD ") + f"{words!r:45} -> {r['day']:10} | {r['what_to_do_next'][:150]}")
        assert ok
    for amt, phrase in (("410", "acceptable"), ("100", "below"), ("600", "more than"), ("180", "acceptable")):
        r = run_tool(code, v, {"amount": amt, "product": "p1"}); print(amt, "->", r["what_to_do_next"][:120]); assert phrase in r["what_to_do_next"]
    print("CHECK PAYMENT OK")


test_check_payment()
