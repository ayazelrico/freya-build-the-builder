"""Check the deployed mock against every answer in test-customers.json (status code and body)."""
import json, sys, urllib.request, urllib.error, concurrent.futures as cf
BASE = sys.argv[1].rstrip("/") + "/voice/v1/"
D = json.load(open(sys.argv[2]))
def post(svc, data):
    req = urllib.request.Request(BASE + svc, data=json.dumps({"data": data, "call": {"ani": "x", "lang": "tr"}}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "mock-check"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, json.load(e)
jobs = []
for c in D["customers"]:
    for svc, v in c["services"].items():
        if "http" in v:
            jobs.append((svc, {"customerNo": c["customerNo"], "cardNumber": "x"}, v))
        else:
            for card, w in v.items():
                if "http" in w: jobs.append((svc, {"cardNumber": card, "customerNo": c["customerNo"]}, w))
                else:
                    for wk, z in w.items(): jobs.append((svc, {"cardNumber": card, "newStatementWeek": int(wk)}, z))
def run(j):
    svc, data, exp = j
    st, body = post(svc, data)
    ok = st == exp["http"] and body == exp.get("response", exp.get("yanit"))
    return ok, svc, data, st, exp["http"]
bad = 0
with cf.ThreadPoolExecutor(16) as ex:
    for ok, svc, data, st, want in ex.map(run, jobs):
        if not ok:
            bad += 1; print("MISMATCH", svc, data, "got", st, "want", want)
print(f"{len(jobs) - bad}/{len(jobs)} answers match")
# a customer and a card that are not in the data
for svc, data in (("cards.list", {"customerNo": "11111111"}), ("cards.balance", {"cardNumber": "999999******0000"}), ("statement.week.decide", {"cardNumber": "999999******0000", "newStatementWeek": 2}), ("cards.balance", {})):
    st, body = post(svc, data); print("unknown:", svc, st, body["result"]["code"])
