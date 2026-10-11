"""Brief E (numeric codes, code-only close_call, per-band offer plans, no callbacks, percent floors). No network."""
import json, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder import generate
from tests.test_runtime import node_code, tool, run, run_tool

spec = json.load(open(ROOT / "fixtures/fake/brief-e.llm-spec.json")); wf = generate.build(spec, json.load(open(ROOT / "fixtures/fake/openapi-e.json")))
tp = wf["nodes"]["third_party"]
assert not tp["tools"] and "call schedule_callback with" not in tp["task_message"], "callbacks are disabled in brief E"
v = {"customer_id": "c", "first_name": "J", "last_name": "K", "title": "Mr", "now": "2026-12-17T10:00"}   # Thursday
prods = [{"product_id": "p1", "type": "overdraft", "account_last4": "1234", "overdue": 400, "days_overdue": 12},
         {"product_id": "p2", "type": "instalment_loan", "overdue": 60, "days_overdue": 45}]
for i, p in enumerate(prods):
    for k, x in p.items(): v[f"load_account_response.data.products.{i}.{k}"] = x
run(node_code(wf, "setup"), v); run(node_code(wf, "compute"), v)
P = json.loads(v["products_json"])
for p in P: print(p["product_id"], "floor", p["floor"], "deadline", p["deadline"], "plan", [(a["amount_rule"], a["date"]) for a in p["plan"]])
assert P[0]["floor"] == 120 and P[1]["floor"] == 25          # 30 % of 400; 30 % of 60 = 18 -> minimum 25
assert P[0]["deadline"] == "2026-12-23"                     # 10 calendar days = 27 Dec (Sunday) -> business day before = 23 Dec (24 holiday)
assert [a["date"] for a in P[0]["plan"]] == ["2026-12-23"]    # band 1: full amount on the limit date
code = [t for t in wf["nodes"]["negotiate"]["tools"] if t["function"]["name"] == "check_payment"][0]["function"]["parameters"]["properties"]["code"]["default"]
for words, prod in (("the 24th", "p1"), ("next Monday", "p1"), ("the 28th", "p1")):
    r = run_tool(code, v, {"day": words, "product": prod}); print(f"{words!r:14} -> {r['day']} | {r['what_to_do_next']}")
v2 = dict(v, end_path_outcome="24", end_path_reason="", end_path_role="hardship", transfer_done_queue="hardship")
run(node_code(wf, "finalize"), v2); print("hardship transfer ->", v2["close_outcome"], repr(v2["close_reason"]))
assert v2["close_outcome"] == "52"
cfg = {"body": {"customer_id": "c", "code": v2["close_outcome"]}}
run(wf["tools"][0]["pre_process_code"], v2, config=cfg); print("close body", cfg["body"])
print("FAKE E OK")
