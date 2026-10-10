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
