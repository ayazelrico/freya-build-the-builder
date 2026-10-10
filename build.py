"""The builder. Brief files in, a phone agent on Freya out.

    python3 build.py briefs/brief-a.md [briefs/brief-b.md ...] [--openapi tools/openapi.json] [--slot NAME] [--spec SPEC.json]

Steps: brief -> SPEC (Claude) -> workflow (deterministic code) -> dry-run validation -> save + publish on Freya
-> export. Every step is written to traces/<slot>-<time>.jsonl.
"""
import argparse, json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import freya
from builder import generate
from builder.trace import Trace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("briefs", nargs="+")
    ap.add_argument("--openapi", default=str(ROOT / "tools/openapi.json"))
    ap.add_argument("--slot", help="Freya workflow slot (default: the last brief's file name)")
    ap.add_argument("--spec", help="use this SPEC file instead of extracting one (for testing the generator)")
    ap.add_argument("--no-save", action="store_true", help="build and validate only")
    a = ap.parse_args()

    slot = a.slot or pathlib.Path(a.briefs[-1]).stem
    out = ROOT / "out"; out.mkdir(exist_ok=True)
    trace = Trace(ROOT / "traces" / f"{slot}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    trace.event("inputs", briefs=a.briefs, openapi=a.openapi, slot=slot)
    openapi_text = pathlib.Path(a.openapi).read_text()

    if a.spec:
        spec = json.loads(pathlib.Path(a.spec).read_text())
        trace.event("spec_loaded", path=a.spec)
    else:
        from builder.extract import extract_spec
        spec = extract_spec([(pathlib.Path(b).name, pathlib.Path(b).read_text()) for b in a.briefs], openapi_text, trace)
    (out / f"{slot}.spec.json").write_text(json.dumps(spec, indent=1))
    trace.event("spec_written", path=f"out/{slot}.spec.json", outcomes=len(spec.get("outcomes") or []))

    wf = generate.build(spec, json.loads(openapi_text))
    (out / f"{slot}.workflow.json").write_text(json.dumps(wf, indent=1))
    trace.event("workflow_generated", nodes=len(wf["nodes"]), bytes=len(json.dumps(wf)))

    if not a.no_save:
        freya.validate_workflow(slot, wf)
        trace.event("dry_run_ok")
        ids = freya.save_workflow(slot, wf, state_file=str(ROOT / ".freya-agents.json"))
        trace.event("saved_on_freya", **ids)
        path = freya.export_workflow(ids["workflow_id"], str(out / f"{slot}.export.workflow.json"))
        trace.event("exported", path=path)
        print(json.dumps(ids))
    trace.close(slot=slot)


if __name__ == "__main__":
    main()
