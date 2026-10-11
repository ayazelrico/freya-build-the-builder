"""The generated code on a brief with other field names and outcome codes (fixtures/fake). No network."""
import json, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder import generate
from tests.test_runtime import node_code, tool, run

spec = json.load(open(ROOT / "fixtures/fake/brief-c.llm-spec.json")); wf = generate.build(spec, json.load(open(ROOT / "fixtures/fake/openapi-c.json")))
v = {"customer_id": "c_x", "first_name": "Ana", "last_name": "Weiss", "title": "Ms", "now": "2026-12-21T10:00"}
run(node_code(wf, "setup"), v); print(v["callback_facts"])
prods = [{"facility_id": "f1", "kind": "overdraft", "iban_last4": "7781", "overdue_amount": 900, "days_in_arrears": 30, "min_due": 150},
         {"facility_id": "f2", "kind": "term_loan", "overdue_amount": 300, "days_in_arrears": 5, "rate": 100}]
for i, p in enumerate(prods):
    for k, x in p.items(): v[f"load_account_response.data.facilities.{i}.{k}"] = x
run(node_code(wf, "compute"), v); print(v["debt_statement"]); print(v["negotiation_facts"][:900])
neg = wf["nodes"]["negotiate"]
pt = tool(wf, "negotiate", "create_promise")
cfg = {"body": {"customer_id": "c_x", "facility_id": "f1", "amount": 150, "pay_on": "24 December 2026"}}
run(pt["pre_process_code"], v, config=cfg); print("24 Dec:", v["promise_block"])
cfg = {"body": {"customer_id": "c_x", "facility_id": "f1", "amount": 150, "pay_on": "2026-12-29"}}
run(pt["pre_process_code"], v, config=cfg); print("29 Dec:", repr(v["promise_block"]))
cb = tool(wf, "third_party", "schedule_callback")
cfg = {"body": {"customer_id": "c_x", "date": "2026-12-22", "time": "5:30 pm"}}
run(cb["pre_process_code"], v, config=cfg); print("callback 22 Dec 17:30:", cfg["body"], repr(v["callback_block"]))
res = {"status": "success", "data": {"ok": True}, "header": {}}
run(pt["post_process_code"], v, result=res)
for path in ("no_arrangement", "handed_over"):
    rw = [r for r in spec["outcomes"] if r["outcome"] == path][0]
    v2 = dict(v, end_path_outcome=rw["outcome"], end_path_reason=rw["reason"], end_path_role=rw["role"])
    if path == "handed_over": v2["transfer_done_queue"] = "care"
    run(node_code(wf, "finalize"), v2); print(path, "->", v2["close_outcome"], v2["close_reason"], "|", v2["farewell_text"])
    cfg = {"body": {"customer_id": "c_x", "status": v2["close_outcome"], "sub_status": v2["close_reason"]}}
    run(wf["tools"][0]["pre_process_code"], v2, config=cfg); print("   close body", cfg["body"])
print("transitions to ends:", [t["target_node"] for t in neg["transitions"]])
print("OK")
