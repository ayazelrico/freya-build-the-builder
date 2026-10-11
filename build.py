"""The builder. Brief files in, a phone agent on Freya out.

    python3 build.py <brief.md> [<more briefs>] [<tool_api.json>] [--slot NAME] [--spec SPEC.json]
    python3 build.py briefs/hidden-1.md briefs/hidden-1.openapi.json        # the submission form's run_command

Steps: brief -> SPEC (Claude) -> workflow (deterministic code) -> dry-run validation -> save + publish on Freya
-> export. Every step is written to traces/<slot>-<time>.jsonl.
"""
import argparse, json, os, pathlib, re, sys, time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import freya
from builder import generate
from builder.trace import Trace


LANG_CODES = {"english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it", "dutch": "nl", "turkish": "tr", "portuguese": "pt"}


def tune_agent_config(workflow_id, spec, trace):
    """The platform fills in agent settings when a workflow is saved. Its turn-taking default (start speaking 0.5 s after
    the caller pauses) cuts talkative callers off mid-sentence, and its speech language defaults to Turkish.
    Give callers time to finish and match the brief's language. The model is left exactly as it is."""
    try:
        wait = float(os.environ.get("TURN_WAIT_SECONDS", "4.0"))
        w = freya.api("GET", f"/api/v2/workflow/{workflow_id}", workspaceId=freya.workspace_id())["workflow"]["workflow"]
        ac = w.get("agent_config") or {}
        tts = ac.setdefault("ttsConfig", {}); stt = ac.setdefault("sttConfig", {})
        tts.setdefault("startSpeakingPlan", {})["waitSeconds"] = wait
        if os.environ.get("SMART_TURN", "0") in ("0", "1"):
            stt.setdefault("additionalSettings", {})["smartTurnEnabled"] = os.environ.get("SMART_TURN", "0") == "1"
        lang = LANG_CODES.get(str(spec.get("language") or "English").strip().lower())
        if lang:
            tts["language"] = lang; stt["language"] = lang
        freya.api("PUT", f"/api/v2/workflow/{workflow_id}", {"workflow": {**w, "agent_config": ac}})
        vs = freya.api("GET", f"/api/v2/versions/workflow/{workflow_id}", workspaceId=freya.workspace_id())["versions"]
        newest = max(vs, key=lambda v: v["versionNumber"])
        if not newest.get("isPublished"):
            freya.api("POST", f"/api/v2/versions/workflow/{workflow_id}/publish", {"versionId": newest["id"]})
        trace.event("agent_config_tuned", wait_seconds=wait, language=lang, version=newest["versionNumber"])
    except Exception as e:
        trace.event("agent_config_tune_failed", error=str(e)[:300])


def smoke_test(workflow_id, wf, trace):
    """One chat turn against the published agent: it must start and speak. Seconds, not minutes."""
    try:
        r = freya.api("POST", "/api/v2/chat/message", {"workflowId": workflow_id, "message": "Hello?", "customerVariables": wf.get("test_variables", {})}, retries=2)
        said = r.get("response") or ""
        trace.event("self_test_chat_turn", ok=bool(said), agent_said=said[:200])
        if r.get("callId"):
            try: freya.api("POST", "/api/v2/chat/end", {"callId": r["callId"]}, retries=1)
            except Exception: pass
    except Exception as e:
        trace.event("self_test_chat_turn", ok=False, error=str(e)[:300])


def doc_text(pth):
    """Text of a brief document. Word, PDF and Excel are converted; tables keep one row per line."""
    suf = pth.suffix.lower()
    if suf == ".docx":
        import docx
        d = docx.Document(str(pth))
        out = [p.text for p in d.paragraphs if p.text.strip()]
        for ti, t in enumerate(d.tables):
            out.append(f"[table {ti + 1}]")
            out += [" | ".join(c.text.strip() for c in row.cells) for row in t.rows]
        return "\n".join(out)
    if suf == ".pdf":
        import pypdf
        return "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(pth)).pages)
    if suf in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(str(pth), data_only=True, read_only=True)
        out = []
        for ws in wb.worksheets:
            out.append(f"[sheet {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                if any(v is not None and str(v).strip() for v in row):
                    out.append(" | ".join("" if v is None else str(v) for v in row))
        return "\n".join(out)
    return pth.read_text(encoding="utf-8", errors="replace")


def is_tool_api(text):
    try:
        d = json.loads(text)
    except Exception:
        return False
    return isinstance(d, dict) and ("openapi" in d or "swagger" in d or "paths" in d)


def detect_language(texts):
    t = " ".join(texts)[:200000]
    tr = sum(t.count(c) for c in "ğşıİĞŞ")
    return "Turkish" if tr > 50 else "English"


def general_mode(a, slot, trace):
    """Cases outside the collections pattern: Claude writes the workflow from the documents (builder/llm_workflow.py)."""
    from builder import llm_workflow
    limit = int(os.environ.get("DOC_CHAR_LIMIT", "60000"))
    docs = []
    for b in a.briefs:      # very large files (e.g. test data dumps) go in as an excerpt that shows their shape
        t = a.texts[b]
        rel = str(pathlib.Path(b).relative_to(pathlib.Path(a.raw_inputs[0]))) if pathlib.Path(a.raw_inputs[0]).is_dir() else pathlib.Path(b).name
        docs.append((rel, t if len(t) <= limit else t[:limit] + f"\n[... excerpt: first {limit} of {len(t)} characters]"))
    lang = detect_language([t for _, t in docs])
    trace.event("general_mode", documents=len(docs), mock_url=a.mock_url, language=lang)

    def validate(wf):
        try:
            freya.validate_workflow(slot, wf); return ""
        except Exception as e:
            return str(e)
    wf = llm_workflow.write_workflow(docs, a.mock_url, trace, validate)
    out = ROOT / "out"; out.mkdir(exist_ok=True)
    (out / f"{slot}.workflow.json").write_text(json.dumps(wf, indent=1))
    n_tools = sum(len(n.get("tools") or []) + len(n.get("pre_actions") or []) for n in wf["nodes"].values()) + len(wf.get("tools") or [])
    trace.event("workflow_generated", steps=len(wf["nodes"]), tools=n_tools, bytes=len(json.dumps(wf)))
    ids = freya.save_workflow(slot, wf, state_file=str(ROOT / ".freya-agents.json"))
    trace.event("saved_on_freya", **ids)
    tune_agent_config(ids["workflow_id"], {"language": lang}, trace)
    smoke_test(ids["workflow_id"], wf, trace)
    path = freya.export_workflow(ids["workflow_id"], str(out / f"{slot}.export.workflow.json"))
    sub = ROOT / "submission"; sub.mkdir(exist_ok=True)
    (sub / f"{slot}.workflow.json").write_text(pathlib.Path(path).read_text())
    trace.event("exported", path=path, submission=f"submission/{slot}.workflow.json", workflow_id=ids["workflow_id"],
                agent_id=ids["agent_id"], steps=len(wf["nodes"]), tools=n_tools)
    print(json.dumps(ids))
    trace.close(slot=slot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("briefs", nargs="+")
    ap.add_argument("--openapi", default=str(ROOT / "tools/openapi.json"))
    ap.add_argument("--slot", help="Freya workflow slot (default: the last brief's file name)")
    ap.add_argument("--spec", help="use this SPEC file instead of extracting one (for testing the generator)")
    ap.add_argument("--no-save", action="store_true", help="build and validate only")
    a = ap.parse_args()
    # Positional inputs: brief files, folders of brief material (a mail, a policy extract, a memo, a code list...)
    # and the tool API file. The tool API file is recognised by its content, not by its extension.
    a.mock_url = next((b.rstrip("/") for b in a.briefs if re.match(r"^https?://", b)), "")
    a.briefs = [b for b in a.briefs if not re.match(r"^https?://", b)]
    files, a.raw_inputs = [], list(a.briefs)
    for b in a.briefs:
        pth = pathlib.Path(b)
        files += sorted(x for x in pth.rglob("*") if x.is_file() and not x.name.startswith(".")) if pth.is_dir() else [pth]
    briefs, apis, skipped, texts = [], [], [], {}
    for pth in files:
        try:
            text = doc_text(pth)
        except Exception as e:
            skipped.append(f"{pth}: {e}"); continue
        if "\x00" in text[:2000]:
            skipped.append(f"{pth}: binary file"); continue
        texts[str(pth)] = text
        if pth.suffix.lower() in (".json", ".yaml", ".yml") and is_tool_api(text):
            apis.append(str(pth))
        else:
            briefs.append(str(pth))
    if apis:
        a.openapi = apis[-1]
    a.has_api = bool(apis)
    a.briefs, a.skipped, a.texts = briefs, skipped, texts
    if not a.briefs:
        sys.exit("no brief file found in the inputs")

    first_dir = [b for b in a.raw_inputs if pathlib.Path(b).is_dir()]
    slot = a.slot or (pathlib.Path(first_dir[0]).name if first_dir else pathlib.Path(a.briefs[-1]).stem)
    out = ROOT / "out"; out.mkdir(exist_ok=True)
    trace = Trace(ROOT / "traces" / f"{slot}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    trace.event("inputs", briefs=a.briefs, openapi=a.openapi, slot=slot, skipped=a.skipped)
    openapi_text = pathlib.Path(a.openapi).read_text()

    if not a.has_api and a.mock_url:
        return general_mode(a, slot, trace)
    if a.spec:
        spec = json.loads(pathlib.Path(a.spec).read_text())
        trace.event("spec_loaded", path=a.spec)
    else:
        from builder.extract import extract_spec
        spec = extract_spec([(pathlib.Path(b).name, a.texts[b]) for b in a.briefs], openapi_text, trace)
    (out / f"{slot}.spec.json").write_text(json.dumps(spec, indent=1))
    trace.event("spec_written", path=f"out/{slot}.spec.json", outcomes=len(spec.get("outcomes") or []))

    wf = generate.build(spec, json.loads(openapi_text))
    (out / f"{slot}.workflow.json").write_text(json.dumps(wf, indent=1))
    n_tools = sum(len(n.get("tools") or []) + len(n.get("pre_actions") or []) for n in wf["nodes"].values()) + len(wf.get("tools") or [])
    trace.event("workflow_generated", steps=len(wf["nodes"]), tools=n_tools, bytes=len(json.dumps(wf)))

    if not a.no_save:
        freya.validate_workflow(slot, wf)
        trace.event("dry_run_ok")
        ids = freya.save_workflow(slot, wf, state_file=str(ROOT / ".freya-agents.json"))
        trace.event("saved_on_freya", **ids)
        tune_agent_config(ids["workflow_id"], spec, trace)
        smoke_test(ids["workflow_id"], wf, trace)
        path = freya.export_workflow(ids["workflow_id"], str(out / f"{slot}.export.workflow.json"))
        sub = ROOT / "submission"; sub.mkdir(exist_ok=True)
        (sub / f"{slot}.workflow.json").write_text(pathlib.Path(path).read_text())
        trace.event("exported", path=path, submission=f"submission/{slot}.workflow.json", workflow_id=ids["workflow_id"], agent_id=ids["agent_id"],
                    steps=len(wf["nodes"]), tools=n_tools)
        print(json.dumps(ids))
    trace.close(slot=slot)


if __name__ == "__main__":
    main()
