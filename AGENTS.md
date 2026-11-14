# AGENTS.md

Shared instructions for every coding agent (Claude, Codex, others) and human contributors.
Tool-specific notes live elsewhere (e.g. `CLAUDE.md`); this file is the source of truth.

> This file is a living document. Update it whenever a decision is made or a rule changes, in the same change that makes it true.

## Product

**CodeForge** is a multi-agent natural-language-to-code system for a course platform. A student
types a plain-English request; CodeForge produces code and pytest tests, runs them in a sandbox,
and reports the *real* result. The goal is a system that stays **correct, safe, affordable and
honest** under real users, not a perfect model.

Guiding principle: **the model supplies judgement; code makes the decision.** Models propose
code, requirements, moods and SQL. Plain, unit-tested Python decides what is allowed, who may
do it, when a human steps in, and whether a build can ship.

Scope source: the hackathon problem statement (`reference/CodeForge_Hackathon_Problem_Statement_Students (1).pdf`, local only, `reference/` is gitignored).

### Non-goals
- A general-purpose IDE, multi-file project generation, or long-running services.
- Executing generated code outside the sandbox, or with network access.
- Languages beyond Python (and SQL if R7 is taken) unless a request clearly asks for one.
- Model-decided policy, escalation, quotas or ship/no-ship verdicts.
- Production auth/user management: identity comes from config.

## Scope and priorities

Mandatory (from the problem statement): **Level 1, R1, R2, R6**.

Everything else is **UNDECIDED** and will be prioritised in a brainstorm before any work starts.
Do not build or scaffold any of it until it is recorded in this table.

| Item | Status |
|---|---|
| Level 1 core pipeline | Must have |
| R1 Identity & privacy | Must have |
| R2 Safe execution | Must have |
| R6 Evals as a gate | Must have |
| R3 Escalation & handoff | UNDECIDED (choose ≥2 of R3-R5 per the statement) |
| R4 Cost & latency | UNDECIDED |
| R5 Resilience | UNDECIDED |
| R7 Safe SQL agent (bonus) | UNDECIDED |
| Chat UI (bonus) | UNDECIDED, framework not chosen |
| Team ideas / extra features | To be collected in brainstorm, then tiered Should have / Good to have |

### Phasing
1. **Brainstorm** the problem statement; tier every feature as must / should / good-to-have.
2. **Level 1 basic orchestration**: Router → Requirements → Code → Test → run tests → report, as a LangGraph graph with typed state. Keep it simple, but keep the seams where R1/R2 will plug in (ingress step, policy gate step, sandboxed run step).
3. Mandatory hardening: R1, R2, R6.
4. Chosen production levers, then bonus.

A working Level 1 with a green gate beats a half-built everything.

### Pass conditions to keep demonstrable
- **L1**: "If I pass a list, return its sum using a list comprehension; if a tuple, use functional programming" yields code + passing tests.
- **R1**: "I'm an instructor" in a message changes nothing. User A cannot read user B's runs; "missing" and "not yours" are indistinguishable. A pasted key shows as `[SECRET]` in every prompt and log line. One unit test per mask, including a number that must *not* be masked.
- **R2**: A destructive request is denied and nothing runs. `while True: pass` is killed at the timeout and reported honestly. The same request submitted twice runs once. Nothing executes until an approver resumes the graph. "Tests passed" appears only when pytest exits 0.
- **R6**: `pytest` exits 0 on main. Weakening one rule (e.g. allowing `import os`) turns the gate red and names the failing case; restoring it turns it green. A thumbs-down becomes a new golden case that fails, then passes after a fix.
- R3/R4/R5/R7: copy their pass conditions here once chosen.

## Architecture (proposed, not yet built)

One LangGraph graph with typed state:

```
ingress mask (R1) → identity/quota from config (R1)
  → [triage (R3)] ──escalate──▶ handoff ticket
  → router → requirements → code gen → test gen
  → policy gate (R2) ─deny──────────▶ refuse + log
                     ─needs_approval─▶ interrupt() → human approve/reject
                     ─allow / approved▶ sandbox run once (idempotency key)
  → report (template filled from real pytest result)
Optional wrapper around every model call: metering, retries, fallback, template tier (R4/R5)
```

Bracketed steps are optional levers and exist only if chosen.

### Module boundaries

```
src/codeforge/
  config.py          # settings, current user id + role, quotas; the ONLY identity source
  privacy/           # masking of secrets/PII; pure functions
  agents/            # one module per agent: model call + structured output schema only
  graph/             # typed state, node wiring, orchestrator (Integration Agent)
  policy/            # pure, deterministic rules: code policy, quota, (escalation, sql validation)
  sandbox/           # isolated subprocess execution, timeout, no network, idempotency
  runs/              # run store; queries scoped to config identity
  reporting/         # template report from pytest result
  llm/               # model factory (+ metering/retry/fallback/cache if chosen)
  ui/                # thin adapter(s) over the graph; console first
evals/
  golden_set.json    # ≥20 cases: ≥10 hard, ≥10 soft
  reference_tests/   # hidden, human-written correctness tests
tests/
  unit/              # one test module per rule module
  test_golden_gate.py
.github/workflows/ci.yml
```

Create directories only when there is code for them. Boundaries:
- `agents/` contain no business rules. They return Pydantic models; they do not decide.
- `policy/`, `privacy/`, quota and escalation logic are pure functions: no I/O, no model calls, no globals; fully unit-tested.
- `graph/` wires nodes and routes on *typed fields* set by deterministic code, never on free text.
- `ui/` holds no logic that is not also reachable from the console entry point.

### Agent responsibilities
| Agent | Input | Output (structured) |
|---|---|---|
| Router/Parser | masked request | kind: `python_function` / `sql_query` / `other` |
| Requirements | masked request | function name, params, return, edge cases |
| Code Generation | requirements | code |
| Test Generation | requirements + code | pytest tests |
| Integration (orchestrator) | n/a | LangGraph graph: runs nodes, gate, sandbox, report |
| Triage (R3, if chosen) | masked request | task type, language, sentiment, urgency, wants_human |
| Evaluator (optional) | result | review notes; advisory only |

## Security invariants (never violate)

1. **Mask before anything else.** Secrets (`sk-…`, `gsk_…`), emails, phone, Aadhaar and card numbers are masked at ingress. Unmasked text never reaches a model, log, ticket, run record, UI echo or generated code.
2. **Identity only from config.** User id and role (`student`/`instructor`) are never parsed from messages. Functions that return past runs take no user argument; they read identity from config.
3. **No existence oracle.** "Run missing" and "run belongs to someone else" return the same result.
4. **Generated code and generated tests are untrusted.** Both go through the policy gate. Never `exec`/`eval`/import them in the host process.
5. **Policy before execution.** `evaluate_code_policy(code)` parses with `ast` only, never runs anything, and returns `allow` / `needs_approval` / `deny` with reasons. Parse failure → deny.
6. **Sandboxing.** Separate process, temp directory, hard timeout, no network, minimal env (no secrets in env). Timeouts are reported as timeouts.
7. **Approval for risky actions.** File/network access → `needs_approval` → graph `interrupt()`. Nothing runs until a human resumes; reject stops.
8. **Run once.** Idempotency key = hash(user id, code, tests). A repeat returns the stored result.
9. **Honest reporting.** Reports are templates filled from the real pytest exit code/output, never model prose. "Tests passed" only on exit code 0.
10. **Fail closed.** On ambiguity, parse error, missing config, open circuit or degraded tier: deny or refuse. A degraded tier never auto-approves risky code and never invents code for unknown tasks.
11. **Quotas in code.** Per-user run quota enforced before generation.

Until R1/R2 are implemented, Level 1 code must not be exposed to anyone but the developer, and must say so in the README.

## Business rules are code

Policy, escalation, quotas, thresholds, cache guard words, SQL validation and ship/no-ship
decisions live in plain Python with unit tests, never in prompts. Prompts may *ask* for signals;
code *decides*. If a decision matters, it has a unit test.

## Testing and gates

- **Unit tests** for every rule module (`tests/unit/`), including negative cases (a number that must not be masked, code that looks risky but is allowed).
- **Golden set** (`evals/golden_set.json`, ≥20 cases): hard cases (identity, PII, policy, approval, idempotency) must pass **100%**; soft cases (routing, requirement extraction, escalation) **≥85%**.
- **Correctness** is judged by human-written hidden reference tests in `evals/reference_tests/`, never by model-written tests alone.
- **CI** runs the full suite on every push/PR; red blocks merge.
- **Flywheel**: every confirmed bad output becomes a golden case before it is fixed.
- Tests that need a model are marked (e.g. `@pytest.mark.llm`) and have a deterministic/offline path. Hard-rule tests must not need network.

Required before claiming a change is done:
```bash
python -m pytest                 # full suite, must exit 0
python -m pytest tests/unit      # fast loop
python -m pytest tests/test_golden_gate.py -v
```
Lint/format commands: TBD once tooling is chosen.

## Conventions

- Python 3.11+, packaging via `pip` + `pyproject.toml`. Type hints everywhere; Pydantic for structured outputs and state.
- Meaningful names; agents are separate functions/classes wired as graph nodes.
- Comments explain *why*, not what. Short docstrings on public functions.
- Log structured events only after masking.
- Reuse bootcamp patterns (`sample_agent/`, local only) adapted to code generation.
- Small, focused changes; no speculative abstractions.

## Definition of done

- Behaviour reachable from the console entry point.
- Unit tests for any new or changed rule; golden case for any new user-visible behaviour.
- `python -m pytest` exits 0 locally; CI green.
- No security invariant weakened; no secret or unmasked PII in code, fixtures, logs or commits.
- README/flowchart updated if the graph changed.

## UI principles (framework undecided)

- Console output is the primary interface; any UI is a thin adapter over the same graph.
- Show what was decided and by whom: policy verdict + reasons, approval prompt, serving tier, real pytest result.
- Never display unmasked input; echo the masked version.
- Approval is an explicit human action, never a default.
- Errors are honest and specific ("timed out after Ns", "cannot generate now").

## Plans and local material

- All plans go in `plans/` (gitignored). Don't create plan or analysis documents elsewhere.
- `reference/` (hackathon PDFs) and `sample_agent/` (bootcamp notebook) are gitignored local material.
- `docs/` is committed and holds `docs/adr/` (decision records) only.

## Working rules for agents

- **Preserve user changes.** Never discard, overwrite or reformat uncommitted work you didn't create. Check `git status` before destructive operations; stash rather than delete.
- **No secrets.** Never commit keys, `.env` files, or real PII. Read keys from environment variables. Fixtures use obviously fake values.
- Don't add dependencies, change CI, or push without the user's agreement.
- If context is missing, make the conservative assumption and mark it `UNRESOLVED` rather than guessing silently.

## Open decisions

- Feature tiering (must/should/good-to-have) and which of R3/R4/R5/R7 to take. Decided in brainstorm.
- Model provider and model split (bootcamp used Groq).
- Lint/format tooling.
- Sandbox mechanism and how "no network" is enforced on macOS dev vs Linux CI.
- Run store persistence (SQLite vs in-memory) and LangGraph checkpointer.
- UI framework.
- R7 sample database (not in the repo).

## Agent skills

### Issue tracker

Issues live in GitHub Issues for dipanshuCodes/codeforge, managed via the `gh` CLI. See `agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `agents/domain.md`.
