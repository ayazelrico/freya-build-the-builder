"""Run cases against an agent and score them from the bank's ledger and the judge's reading of the conversation.

    python tools/run_cases.py <agent_id> [--brief A|B] [--cases public-test-set.json] [--out results/run.json] [--reps 3] [--style talkative]

Needs FREYA_API_KEY (your workspace) and FREYA_BANK_TEAM_KEY (any secret of 16+ characters your team picks, the same one every time).
"""
import argparse, hashlib, json, os, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import freya
from score import http, score_ledger

PERSONA = """OUTPUT RULE: Write only the words you say on the phone. No stage directions, no brackets. One or two short sentences per turn, then wait for the other side.

WHO YOU ARE: {who}

WHAT HAPPENS IN THIS CALL: {script}

RULES:
- Answer what you are asked. Do not volunteer information nobody asked for.
- When you give a number or a date, say all of it in one turn. Never stop halfway through.
- Do not invent dates, amounts or facts that are not written above. If asked something that is not covered, give a short neutral answer.
- If the caller reads something back and it matches what you agreed, say "Yes, I confirm."
- When the caller says goodbye, say "Thank you, goodbye." and say nothing more."""

# How a customer talks. The facts of the case stay the same, only the way of saying them changes.
STYLES = {
    "pieces": "HOW YOU TALK: you give long numbers and dates in two parts. Say the first half, stop, and give the rest in your next turn or when asked. This replaces the rule about saying all of it in one turn.",
    "corrects": "HOW YOU TALK: the first time you say a day or an amount, you say a slightly different one first and correct yourself in the same sentence, like 'the 21st, sorry, I mean the 20th'. The corrected value is the one written above. Do this once or twice in the call, not more. Never do it with a security answer: those you say right the first time unless the text above says otherwise.",
    "talkative": "HOW YOU TALK: you talk a lot. Before most answers you add one or two sentences about your day, the traffic or how busy work is. Once in the call you mention that your cousin's wedding is on the 30th. It has nothing to do with any payment, and you never offer it as a payment day.",
    "asks_back": "HOW YOU TALK: twice in the call, before you answer, you ask a short question back, like 'why do you need that?' or 'which account is this about?'. Whatever the caller replies, you then give your answer.",
    "in_words": "HOW YOU TALK: you say every amount and every date in words and never in digits, like 'four hundred and fifty-five' and 'the twenty-second of October'. Postcodes, years and other codes you say digit by digit.",
}

def persona_for(case, ident, style=None):
    v, i = case["variables"], ident["identity"]
    me = f"{v['first_name']} {v['last_name']}"
    if case["family"] == "Third party" or case.get("third_party"):
        who = f"You are NOT {me}. You answered this phone. You do not know {me}'s security answers and you would not give them. The text below says who you are."
    else:
        say = {"date_of_birth": "Your date of birth is {} (say it in words, like '14 March 1988').", "phone_last4": "The last four digits of your phone number on file are {}.",
               "postcode": "The postcode of your registered address is {}.", "birth_year": "Your year of birth is {}.",
               "company_number": "Your company number is {}.", "founded_year": "The company was founded in {}."}
        who = f"You are {me}. " + " ".join(say.get(k, "Your " + k.replace("_", " ") + " is {}.").format(x) for k, x in i.items()) + " Give these only when asked, and give the wrong ones where the text below says so."
    style = style or case.get("style")
    text = PERSONA.format(who=who, script=case["script"]) + ("\n\n" + STYLES[style] if style else "")
    return {"name": case["id"] + " " + case["title"] + (f" [{style}]" if style else ""), "prompt": text, "successCriteria": "All of these are true:\n- " + "\n- ".join(case["checks"]), "tags": ["hackathon", "brief-" + case["brief"]]}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("agent_id"); ap.add_argument("--brief"); ap.add_argument("--cases", default=str(ROOT / "public-test-set.json")); ap.add_argument("--out"); ap.add_argument("--only"); ap.add_argument("--reps", type=int, default=1); ap.add_argument("--style", choices=sorted(STYLES)); ap.add_argument("--rerun-if-slow", type=int, default=0)
    a = ap.parse_args()
    cases = [c for c in json.load(open(a.cases)) if (not a.brief or c["brief"] == a.brief) and (not a.only or c["id"] in a.only.split(","))]
    ident = {c["id"]: {"identity": c["identity"]} for c in cases}
    store = ROOT / ".personas.json"; ids = json.load(open(store)) if store.exists() else {}
    # a persona is recreated whenever its text changes, so an edited case never runs with a stale customer
    spec = {c["id"]: persona_for(c, ident[c["id"]], a.style) for c in cases}
    key = {i: i + ":" + hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:10] for i, p in spec.items()}
    new = [c for c in cases if key[c["id"]] not in ids]
    if new:
        made = freya.create_personas([spec[c["id"]] for c in new])["personas"]
        ids.update({key[c["id"]]: p["id"] for c, p in zip(new, made)}); json.dump(ids, open(store, "w"), indent=1)
    ids = {c["id"]: ids[key[c["id"]]] for c in cases}
    (ROOT / "results").mkdir(exist_ok=True)
    reps, total_s = [], 0
    for rep in range(a.reps):
        for attempt in range(1 + a.rerun_if_slow):                   # organisers: a run made while the model was slow is thrown away and repeated
            rows, sim_id, it_id, status, took, med = run_once(a.agent_id, cases, ids)
            if med <= 10 or attempt == a.rerun_if_slow: break
            print(f"-- run discarded: median slowest turn {med:.0f} s. Waiting 5 minutes, then repeating it.\n", flush=True); time.sleep(300)
        reps.append(rows); total_s += took
        if a.reps > 1: print(f"-- run {rep + 1} of {a.reps}: {sum(r['pass'] for r in rows)} / {len(rows)} passed, {took:.0f} s\n")
    need = a.reps                                                # a customer counts only when every run passes
    final = [{"id": c["id"], "family": c["family"], "passes": sum(r[k]["pass"] for r in reps), "runs": a.reps, "pass": sum(r[k]["pass"] for r in reps) >= need} for k, c in enumerate(cases)]
    n = sum(f["pass"] for f in final)
    if a.reps > 1:
        for f in final: print(("PASS" if f["pass"] else "FAIL"), f["id"], f"{f['passes']}/{f['runs']}")
    print(f"\n{n} / {len(final)} passed (bank records and conversation checks){'' if a.reps == 1 else f', a customer counts with {need} of {a.reps} runs'}. Last simulation {sim_id}, status {status}, {total_s:.0f} s.")
    with open(ROOT / "results" / "log.jsonl", "a") as f:      # one line per run, the record of how the score moved over time
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "agent_id": a.agent_id, "brief": a.brief, "runs": a.reps, "passed": n, "total": len(final), "seconds": round(total_s), "failed": [f["id"] for f in final if not f["pass"]]}) + "\n")
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"agent_id": a.agent_id, "simulation_id": sim_id, "iteration_id": it_id, "seconds": round(total_s), "passed": n, "total": len(final), "runs": a.reps, "final": final, "rows": reps[-1], "all_rows": reps}, open(a.out, "w"), indent=1)

def run_once(agent_id, cases, ids):
    """One simulation: every case once. Returns the scored rows."""
    sessions = {c["id"]: http("/v1/practice/sessions", {"case": c["id"]})["variables"] for c in cases}
    t0 = time.time()
    sim_id, it_id, status = freya.run_simulation(agent_id, f"cases {time.strftime('%H:%M:%S')}", {ids[c["id"]]: sessions[c["id"]] for c in cases})
    took = time.time() - t0
    judge = {r["personaId"]: r for r in freya.get_iteration(sim_id, it_id)["runs"]}
    rows = []
    for c in cases:
        led = http("/v1/practice/ledger/" + sessions[c["id"]]["customer_id"])
        r = score_ledger(c, led)
        j = judge.get(ids[c["id"]], {})                      # the conversation checks, read from the transcript by the judge model
        if j.get("outcome") != "pass": r["failed"].append("conversation: " + " ".join(str(j.get("reason") or "no verdict").split())[:400])
        r["pass"] = not r["failed"]
        rows.append({"id": c["id"], "level": c["level"], "family": c["family"], "pass": r["pass"], "failed": r["failed"], "call_id": j.get("callId"), "tools": [x["tool"] for x in led["calls"]], "customer_id": sessions[c["id"]]["customer_id"]})
        print(("PASS" if r["pass"] else "FAIL"), c["id"], f"{c['level']:<6}", f"{c['family']:<14}", "|", " > ".join(x["tool"].replace("verify_identity", "verify").replace("create_promise", "promise") for x in led["calls"]) or "(no tool calls)")
        for f in r["failed"]: print("       -", f[:260])
    # How long the phone agent kept the customer waiting. A call whose customer hung up after long silences says
    # something about the speed of the model at that moment, not only about the agent.
    waits = []
    for r in rows:
        if not r["call_id"]: continue
        try: call = freya.get_call(r["call_id"])
        except Exception: continue
        last_user, worst = None, 0.0
        for m in call.get("messages", []):
            t = m.get("secondsFromStart")
            if t is None: continue
            if m.get("role") == "user": last_user = t
            elif last_user is not None: worst = max(worst, t - last_user); last_user = None if m.get("role") == "assistant" else last_user
        r["slowest_turn_s"] = round(worst, 1); r["ended"] = call.get("endedReason"); waits.append(worst)
    if waits:
        waits.sort(); med = waits[len(waits) // 2]; hung = sum(r.get("ended") == "customer-ended-call" and not r["pass"] for r in rows)
        print(f"\nslowest agent turn per call: median {med:.0f} s, worst {waits[-1]:.0f} s. Failed calls where the customer hung up: {hung}.")
        if med > 10: print("WARNING: the phone agent was slow in this run. If the same agent is fast in another run, the model was busy and this score is too low.")
    return rows, sim_id, it_id, status, took, (med if waits else 0)

if __name__ == "__main__": main()
