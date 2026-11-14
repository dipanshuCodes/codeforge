# CLAUDE.md

@AGENTS.md

All shared rules, architecture, security invariants and definition of done are in `AGENTS.md`
(imported above). This file only adds Claude Code-specific operating notes.

## Before starting work
- Check the Scope table in `AGENTS.md`. If a task touches an UNDECIDED item (R3/R4/R5/R7, UI), ask before building.
- Read `CONTEXT.md` and relevant ADRs if they exist; use their vocabulary.
- Follow the phasing. Don't start a later phase while Level 1 or the gate is red.

## How to work
- For non-trivial changes (new agent, graph change, policy rule), propose a short plan first.
- Rule changes go test-first: write or extend the unit test, watch it fail, then change the rule.
- Never weaken a hard golden case or a security invariant to make a test pass. Stop and report instead.
- Use subagents for broad searches; keep raw output out of the main context.
- Use the `gh` CLI for issues/PRs (see `agents/issue-tracker.md`).

## Verification
Run before saying something works:
- `python -m pytest tests/unit` while iterating; `python -m pytest` before finishing.
- For graph changes, also run the console entry point on the L1 example and one denied request.
- For UI changes, launch the UI and exercise the approval and deny paths; say so if you couldn't.
Report the actual exit code and failing test names, not a summary of intent.

## Safety
- Never run generated code outside the sandbox module, even "just to check".
- Never print, log or paste real keys/PII into prompts, commits or scratch files. Use fake fixtures.
- Don't commit, push, add dependencies or edit CI unless asked.
- Leave the user's uncommitted changes alone.
- Write plans to `plans/`. `plans/`, `reference/` and `sample_agent/` are gitignored local material; ADRs live in `docs/adr/` and are committed.
- This file and `AGENTS.md` change often early on. When a decision is made, propose the edit to them right away. Read them, don't rely on them in code.
