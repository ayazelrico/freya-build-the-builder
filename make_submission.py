"""Write submission.json for the final round, from what the builder run left behind.

    python3 make_submission.py final --mock-url https://... [--team NAME] [--member "Name <email>"]

Takes submission/<name>.workflow.json and the newest traces/<name>-*.log, checks that both are committed and pushed,
and writes submission.json with the repository URL and the current commit.
"""
import argparse, json, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--mock-url", required=True)
    ap.add_argument("--team", default="ayaz-solo")
    ap.add_argument("--member", action="append", default=[])
    ap.add_argument("--case", default="finals/case")
    a = ap.parse_args()
    problems = []
    wf = ROOT / "submission" / f"{a.name}.workflow.json"
    logs = sorted((ROOT / "traces").glob(f"{a.name}-*.log"))
    if not wf.exists():
        problems.append(f"missing {wf.relative_to(ROOT)}")
    if not logs:
        problems.append(f"missing traces/{a.name}-*.log")
    workflow = str(wf.relative_to(ROOT))
    trace = str(logs[-1].relative_to(ROOT)) if logs else ""
    tracked = git("ls-files", workflow, trace)
    for f in (workflow, trace):
        if f and f not in tracked:
            problems.append(f"{f} is not committed")
    if git("status", "--porcelain", "submission", "traces"):
        problems.append("submission/ or traces/ has uncommitted changes")
    if git("rev-parse", "HEAD") != git("rev-parse", "@{u}"):
        problems.append("the commit is not pushed")
    members = []
    for m in a.member:
        mm = re.match(r"\s*(.*?)\s*<(.+)>\s*$", m)
        members.append({"name": mm.group(1), "email": mm.group(2)} if mm else {"name": m, "email": ""})
    sub = {
        "team": a.team,
        "members": members,
        "repo": git("remote", "get-url", "origin").removesuffix(".git"),
        "commit": git("rev-parse", "HEAD"),
        "run_command": f"python3 build.py {a.case} {a.mock_url} --slot {a.name}",
        "workflow": workflow,
        "trace": trace,
        "mock_url": a.mock_url,
    }
    (ROOT / "submission.json").write_text(json.dumps(sub, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(sub, indent=2, ensure_ascii=False))
    if problems:
        print("\nNOT READY:\n- " + "\n- ".join(problems), file=sys.stderr)
        sys.exit(1)
    print("\nready: submission.json")


if __name__ == "__main__":
    main()
