"""Write submission.json for the form on the hackathon page, from what the builder runs left behind.

    python3 make_submission.py hidden-1 hidden-2 [--team NAME]

For each name it takes submission/<name>.workflow.json and the newest traces/<name>-*.log, checks that both exist,
and prints the JSON with the repository URL and the current commit. Commit and push first, so the commit holds the files.
"""
import argparse, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--team", default="ayaz-solo")
    a = ap.parse_args()
    workflows, traces, problems = {}, {}, []
    for n in a.names:
        wf = ROOT / "submission" / f"{n}.workflow.json"
        logs = sorted((ROOT / "traces").glob(f"{n}-*.log"))
        if not wf.exists():
            problems.append(f"missing {wf.relative_to(ROOT)}")
        if not logs:
            problems.append(f"missing traces/{n}-*.log")
        workflows[n] = str(wf.relative_to(ROOT))
        traces[n] = str(logs[-1].relative_to(ROOT)) if logs else ""
        tracked = git("ls-files", workflows[n], traces[n])
        for f in (workflows[n], traces[n]):
            if f and f not in tracked:
                problems.append(f"{f} is not committed")
    if git("status", "--porcelain", "submission", "traces"):
        problems.append("submission/ or traces/ has uncommitted changes")
    if git("rev-parse", "HEAD") != git("rev-parse", "@{u}"):
        problems.append("the commit is not pushed")
    remote = git("remote", "get-url", "origin").removesuffix(".git")
    sub = {
        "team": a.team,
        "repo": remote,
        "commit": git("rev-parse", "--short", "HEAD"),
        "run_command": "python3 build.py {brief_path} {tool_api_path}",
        "workflows": workflows,
        "traces": traces,
    }
    (ROOT / "submission.json").write_text(json.dumps(sub, indent=2) + "\n")
    print(json.dumps(sub, indent=2))
    if problems:
        print("\nNOT READY:\n- " + "\n- ".join(problems), file=sys.stderr)
        sys.exit(1)
    print("\nready: submission.json")


if __name__ == "__main__":
    main()
