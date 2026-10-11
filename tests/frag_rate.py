"""Share of caller messages that end mid-sentence in a run_cases result file."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya
r = json.load(open(sys.argv[1])); frag = tot = 0
for row in r["rows"]:
    if not row.get("call_id"): continue
    for m in freya.get_call(row["call_id"])["messages"]:
        if m["role"] == "user":
            tot += 1; t = m["message"].strip()
            if t and t[-1] not in ".?!": frag += 1
print(f"{sys.argv[1]}: passed {r['passed']}/{r['total']}, cut-off caller messages {frag}/{tot} = {100 * frag // max(tot, 1)}%")
