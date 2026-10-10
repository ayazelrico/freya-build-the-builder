# Freya "Build the Builder": a builder that turns a bank brief into a phone agent

```bash
source env.sh                                   # FREYA_API_KEY, FREYA_BANK_TEAM_KEY, ANTHROPIC_API_KEY
python3 build.py briefs/brief-a.md briefs/brief-b.md --slot my-agent
python3 build.py <final-brief.md> --openapi <its-openapi.json> --slot final-1
```

One command, no manual step: brief(s) + tool API in → a published Freya workflow, its export
(`out/<slot>.export.workflow.json`) and a trace (`traces/<slot>-<time>.jsonl`) out.

## How it works

The phone agent runs on a fixed, small model, and a customer counts only if all three runs pass.
So the builder leaves as little reasoning as possible to that model. Dates, amounts, outcome codes and
mandatory sentences come from code. The model only holds the conversation.

```
brief(s) + openapi.json
  1. SPEC extraction (Claude Opus 5.5)            builder/extract.py, schema in builder/spec_schema.md
     - pass 1: brief -> SPEC (values, rules, sentences, outcome table with semantic roles)
     - pass 2: coverage review against the brief (memos that change rules, missing rules)
     - mechanical checks (placeholders, roles, tool enums, dates) + LLM repair
  2. Workflow generation (deterministic Python)   builder/generate.py
     - tool definitions read from the openapi file (field names, enums), nothing hard-coded
     - nodes: setup -> opening -> third_party | identity -> load_account -> compute -> negotiate -> end_* -> finalize -> goodbye
  3. Runtime code inside the workflow             builder/runtime_code.py
     - code nodes: business days, holidays, per-product band/deadline/floor, the offer sequence
       with exact sentences, a DATE LOOKUP table telling the agent what to offer for any day
     - tool pre-hooks: normalise dates/digits, block a promise or callback that breaks the rules
     - tool post-hooks: add `what_to_do_next` to every result
     - finalize: outcome + reason from what really happened (transfer, promises, notes) and the
       closing words; close_call is a lifecycle tool with baked values
  4. Save + publish on Freya (same slot = update in place), dry-run validation, one chat-turn smoke test
  5. Export + trace
```

## Tests

- `tests/test_runtime.py`: runs the workflow's code nodes and hooks locally on the 13 practice cases.
- `tests/test_fake_c.py`: the same on a made-up raw-material brief with other field names and outcome
  codes (`fixtures/fake/`), to check that nothing depends on the public briefs.
- `tools/run_cases.py`: the kit's simulator runner.

`KIT_README.md` is the organisers' kit README.
