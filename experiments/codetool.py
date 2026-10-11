"""Does a model-called code_exec tool return data to the model? Tiny workflow, chat API."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya
code = ("names = sorted(k for k in dir() if not k.startswith('__'))\n"
        "t = ''\n"
        "try:\n"
        "    t = str(params.get('day_text'))\n"
        "except Exception as e:\n"
        "    t = 'no params: ' + str(e)[:40]\n"
        "vars['day_verdict'] = 'VERDICT for [' + t + '] globals=' + ','.join(names)[:200]\n"
        "return {'verdict': vars['day_verdict']}\n")
wf = {"initial_node": "talk", "system_prompt": "You are a test assistant. Speak English.", "global_nodes": {},
      "test_variables": {"customer_id": "c_test", "now": "2026-10-14T11:00"},
      "nodes": {"talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Which day?"},
                         "task_message": "When the user names a day, CALL check_day with day_text = the user's words, then tell the user exactly what the tool result says. Verdict so far: {{day_verdict}}",
                         "tools": [{"type": "function", "config": {"timeoutMs": 10000},
                                    "function": {"name": "check_day", "handler": "__function__:code_exec",
                                                 "description": "Check a payment day. CALL it every time the user names a day.",
                                                 "parameters": {"type": "object", "properties": {
                                                     "day_text": {"type": "string", "description": "The day in the user's words"},
                                                     "code": {"type": "string", "default": code}}, "required": ["day_text"]}}}],
                         "transitions": [], "max_node_turns": 10}}}
ids = freya.save_workflow("exp-codetool", wf)
print(ids)
r = freya.api("POST", "/api/v2/chat/message", {"workflowId": ids["workflow_id"], "message": "Hi", "customerVariables": wf["test_variables"]})
cid = r.get("callId"); print("1>", r.get("response"))
r = freya.api("POST", "/api/v2/chat/message", {"workflowId": ids["workflow_id"], "callId": cid, "message": "I can pay on Monday the 26th.", "customerVariables": wf["test_variables"]})
print("2>", r.get("response"))
c = freya.get_call(cid)
for m in c["messages"]:
    if m["role"] == "system":
        e = json.loads(m["message"])
        if e.get("event") in ("function_call_start", "function_call_complete", "error"):
            print(e.get("event"), json.dumps(e)[:500])
