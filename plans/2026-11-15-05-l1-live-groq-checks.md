# L1 live Groq checks (issue #3)

Status: draft for team review, 2026-11-15. Owner: Dipanshu. Tracker: §2 Level 1 pipeline.
Issue: https://github.com/dipanshuCodes/codeforge/issues/3

## Goal

Level 1 has only run offline (94 unit tests pass, 1 skipped). Prove it against real Groq and
record the evidence, so R1/R2/R6 can build on live model behaviour. No new features.

## Starting state

- `tests/llm/test_groq_smoke.py` has one `llm`-marked test (router, palindrome). It is skipped
  unless `GROQ_API_KEY` is set. `tests/conftest.py` loads `.env.local` / `.env` through
  `load_env_files`, so the key can come from the shell or from those files.
- `GroqCaller` (`src/codeforge/llm/caller.py`) uses `ChatGroq(...).with_structured_output(schema,
  include_raw=True)`, which uses the default method. We have not checked which method works with
  `openai/gpt-oss-120b`.
- `scripts/trace_pipeline.py` (untracked) traces the real graph node by node and rejects at the
  approval gate. `python -m codeforge` is the console entry point.

## Steps

0. **Claim it.** In `plans/TRACKER.md` §2, set Owner = Dipanshu and Status = `in progress` for
   the Groq smoke test and both live checks. Link this plan from phase 2.
1. **Confirm the key is usable** without printing it (presence check only; never open
   `.env.local`). If it is missing, stop here and ask the user. This blocks everything below.
2. **Smoke test.** `python -m pytest -m llm -v`. Record exit code and result.
   - If it fails on structured output, try the other methods (`json_schema`, `function_calling`,
     `json_mode`) one at a time through `GroqCaller`. Pick the one that works and record why.
   - Any fix to `GroqCaller` or a prompt/schema is test-first: add or extend the offline unit test
     (`tests/unit/test_agents.py`), watch it fail, then change the code.
3. **Smoke coverage.** The one smoke test only covers the router. Add `llm`-marked smoke tests
   for requirements, codegen and testgen, so a failure names the node. (Test code only: no new
   dependencies.)
4. **Live check 1: L1 pass condition.** Run `python -m codeforge` with: "If I pass a list, return
   its sum using a list comprehension; if a tuple, use functional programming". Expected: policy
   verdict `needs_approval` → type `approve` → code + tests run in the sandbox → exit 0 →
   "Tests passed". Capture the full transcript (masked, no key).
5. **Live check 2: Student B.** Run with "delete my home folder". Expected: approval prompt shows
   the code and tests → `reject` → nothing runs, outcome `rejected`, no "Tests passed".
   Note for the record: with the L1 stub this is rejected by a human, not denied by policy.
   Policy `deny` for destructive code is R2 and is not in scope here.
6. **Fix what the runs expose** (prompts, schemas, code-missing-function-name, test import
   path). Each fix gets a failing offline test first. If a fix would weaken a security invariant,
   stop and report instead.
7. **Record evidence.**
   - Plan 02: the structured-output method that works, and both transcripts.
   - `plans/TRACKER.md`: the three rows to `done` with test command + exit code, update "Right
     now" and the Cases-by-node cross-cutting boxes, recolour the diagram if a node changes.
8. **Verify and finish.** `python -m pytest` must exit 0 (report real exit code and any failing
   test names). Open a PR against the default branch (`master`) and link it from the issue. No
   commit, push or CI change without the user's agreement.

## Acceptance (from the issue)

- Both transcripts recorded; "Tests passed" shown only on a real pytest exit 0.
- `python -m pytest` exits 0.
- Tracker §2 rows updated with evidence.

## Risks and assumptions

- **Key availability (UNRESOLVED).** `GROQ_API_KEY` was not in the shell at the start of this
  session. Whether `.env.local` provides it is not yet confirmed.
- **Rate limits / flakiness.** A 429 during a live run is not an L1 bug (retry is R5). Re-run
  once; record the failure honestly if it persists.
- **Model nondeterminism.** Live runs may differ between attempts. Record the transcript that
  was actually produced; do not edit it.
- **Generated code runs in the sandbox only** (`python -I -m pytest`, temp dir). The approval
  step is a real human action: the approver types `approve` (live check 1) or `reject` (check 2).
- **Branch.** The tracker says the L1 commit is on `docs/problem-statement-alignment`, but the
  working branch is `main` while the default branch is `master`. Confirm which branch the PR
  should come from.
- `plans/TRACKER.md` and `scripts/` are uncommitted changes the user already had. Leave them
  as they are apart from the edits in step 0 and 7.

## Out of scope

R1 masking, R2 allowlist/network block/keys, R6 golden set, repair loop, R3, R5, Gradio.
