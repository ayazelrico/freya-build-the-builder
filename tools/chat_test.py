"""Talk to a published workflow turn by turn and print what it says and which tools it called.

    python3 tools/chat_test.py <slot> <customerNumber> "<turn 1>" "<turn 2>" ... [--now 2026-10-12T10:30:00+03:00]
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import freya


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slot"); ap.add_argument("customer"); ap.add_argument("turns", nargs="*")
    ap.add_argument("--now", default="2026-10-12T10:30:00+03:00")
    a = ap.parse_args()
    wid = json.loads((ROOT / ".freya-agents.json").read_text())[a.slot]["workflow_id"]
    vars_ = {"customerNumber": a.customer, "now": a.now}
    call_id = None
    for t in ["Alo?"] + a.turns:
        body = {"workflowId": wid, "message": t, "customerVariables": vars_}
        if call_id: body["callId"] = call_id
        try:
            r = freya.api("POST", "/api/v2/chat/message", body, retries=3)
        except Exception as e:
            print("ERROR", str(e)[:300]); break
        call_id = r.get("callId") or call_id
        print(f"USER : {t}\nAGENT: {r.get('response')}\n")
    if call_id:
        try:
            for m in freya.get_call(call_id).get("messages", []):
                if m["role"] == "system":
                    e = json.loads(m["message"])
                    if e.get("event") == "function_call_start":
                        args = e.get("args") or {}
                        print("  CALL", e.get("function"), json.dumps(args.get("body") or args.get("params") or args.get("url"), ensure_ascii=False)[:200])
                    elif e.get("event") == "function_call_complete":
                        print("  RES ", e.get("function"), json.dumps((e.get("result") or {}).get("status_code")), json.dumps((e.get("result") or {}).get("data"), ensure_ascii=False)[:160])
                    elif e.get("event") == "error":
                        print("  ERR ", e.get("message"))
        except Exception as e:
            print("could not read the call:", str(e)[:200])


if __name__ == "__main__":
    main()
