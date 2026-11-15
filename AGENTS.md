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

Scope source, read in this order (`plans/` is committed; `reference/` is gitignored local material):
1. `plans/2026-11-15-01-problem-statement-alignment.md`: the agreed problem statement and every scope decision.
2. `reference/problem-statement.md`: a condensed summary of the hackathon brief, with all pass conditions and the rubric.
3. `reference/CodeForge_Hackathon_Problem_Statement_Students (1).pdf`: the original brief, the authority when wording is disputed.

Domain vocabulary (Request, Run, Execution, Conversation, Serving tier and others) is defined in `CONTEXT.md`. Use those terms in code, tests and docs.

**Deadline:** submission on 2026-11-15 at 3:30 PM IST.

**Team (3 people; the brief assumes 4):**
- **Dipanshu:** graph design and the Level 1 pipeline.
- **Siyahul:** evals and policies (R1, R2, R6), then R3 and R5.
- **Neha:** Gradio UI and the presentation.

### Non-goals
- A general-purpose IDE, multi-file project generation, or long-running services.
- Executing generated code outside the sandbox, or with network access.
- Languages beyond Python. `sql_query` and `other` Requests get an honest "not supported" report and no code.
- Model-decided policy, escalation, quotas or ship/no-ship verdicts.
- Production auth/user management: identity comes from config.

## Scope and priorities

Mandatory (from the problem statement): **Level 1, R1, R2, R6**. Chosen levers: **R3, R5**
(decided 2026-11-15). Do not build anything not marked Must or Should in this table.

| Item | Status |
|---|---|
| Level 1 core pipeline | Must have |
| R1 Identity & privacy | Must have |
| R2 Safe execution | Must have |
| R6 Evals as a gate | Must have |
| R3 Escalation & handoff | Must have (chosen lever) |
| R5 Resilience | Must have (chosen lever) |
| Chat UI (bonus) | Should have: Gradio, owned by Neha, a thin adapter; drop it if it isn't working by 1:30 PM IST |
| R4 Cost & latency | Good to have, only if time remains. Model names in config keep the door open |
| R7 Safe SQL agent (bonus) | Out: no sample database, and it adds a second policy surface |

### Phasing
1. ~~Brainstorm~~ Done 2026-11-15; see `plans/2026-11-15-01-problem-statement-alignment.md`.
2. **Level 1 basic orchestration**, as a LangGraph graph with typed state. Every node exists from day one:
   - `ingress` → `triage` → `escalation` → `router` → `requirements` → `codegen` → `testgen` → `policy` → `execute` → `report`.
   - Stubs return safe defaults.
   - `execute` is a real subprocess with a timeout from the start.
   - Routing uses typed fields (`kind`, `verdict`).
   - L1 decisions (2026-11-15; details in `plans/2026-11-15-02-l1-node-actions.md`):
     - Runs are stored in SQLite from day one, filtered by the config User.
     - Each model node makes one structured call. Bad output → "cannot generate now"; bad router output → `other`.
     - Policy stub: parse failure → `deny`; everything else → `needs_approval`, so `interrupt()` approval exists in L1.
     - Sandbox in L1: `python -I -m pytest` in a temp dir, 10 s timeout that kills the process group, stripped env (never the Groq key), output cut to 10 KB. The network block, memory cap and Execution key come in R2.
     - The repair edge exists with `max_repair_attempts = 0`; repair logic comes after R1/R2/R6.
     - The outcome is set in code from the pytest exit code. Only exit 0 is "tests passed"; exit 5 (no tests) is never a pass.
3. Mandatory hardening: R1, R2, R6.
4. R3 and R5, then the Gradio UI, then R4 if time remains.

A working Level 1 with a green gate beats a half-built everything.

### Pass conditions to keep demonstrable
- **L1**: "If I pass a list, return its sum using a list comprehension; if a tuple, use functional programming" yields code + passing tests.
- **R1**: "I'm an instructor" in a message changes nothing. User A cannot read user B's runs; "missing" and "not yours" are indistinguishable. A pasted key shows as `[SECRET]` in every prompt and log line. One unit test per mask, including a number that must *not* be masked.
- **R2**: A destructive request is denied and nothing runs. `while True: pass` is killed at the timeout and reported honestly. The same request submitted twice runs once. Nothing executes until an approver resumes the graph. "Tests passed" appears only when pytest exits 0.
- **R6**: `pytest` exits 0 on main. Weakening one rule (e.g. allowing `import os`) turns the gate red and names the failing case; restoring it turns it green. A thumbs-down becomes a new golden case that fails, then passes after a fix.
- **R3**: Student C's message ("THIS IS NOT WORKING!!! get me a human" with a key and an Aadhaar number) opens a P1 ticket containing no key or Aadhaar. A calm request opens no ticket. Two mildly unhappy turns escalate, though neither would alone. The rules have unit tests.
- **R5**: Under chaos (60% of model calls fail), 20 of 20 requests get an answer and the report names the serving tier. In a total outage, template tasks still return code and tests, and an unknown task gets an honest "cannot generate now" plus a ticket, never invented code. The degraded tier never auto-approves risky code.

## Architecture (proposed, not yet built)

One LangGraph graph with typed state. One Conversation is one LangGraph `thread_id`.

```
ingress: mask (R1) → identity + run quota from config (R1) → Duplicate Request lookup (Request key)
  → triage (R3) → escalation rules (R3) ──P1──▶ Ticket + Handoff note (no generation)
                                          ──P2/P3▶ Ticket, then continue
  → router ─sql_query / other─▶ "not supported" report
  → requirements → code gen → test gen
  → policy gate (R2) ─deny──────────▶ refuse + log (counts as a strike)
                     ─needs_approval─▶ interrupt() → human approve/reject
                     ─allow / approved▶ sandbox Execution (Execution key)
  → tests failed? → Repair attempt (max 2; repair 1 changes code only, repair 2 may also change tests) → policy gate again
  → report (template filled from the real pytest result; names the serving tier)
Wrapper around every model call (R5): jittered retry on transient errors only, circuit breaker,
fallback model, then the template tier. A chaos switch injects failures (seeded).
```

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
| Triage (R3) | masked request | language, sentiment (`calm`/`mildly_unhappy`/`angry`), urgency (`low`/`high`), wants_human. No task type: the Router alone decides the kind |
| Handoff summary (R3) | masked ticket fields | 1–2 advisory sentences from the small model; masked again before saving; absent during an outage |
| Evaluator (optional) | result | review notes; advisory only |

## Security invariants (never violate)

1. **Mask before anything else.** Secrets (`sk-…`, `gsk_…`), emails, phone, Aadhaar and card numbers are masked at ingress. Unmasked text never reaches a model, log, ticket, run record, UI echo or generated code.
2. **Identity only from config.** User id and role (`student`/`instructor`) are never parsed from messages. Functions that return past runs take no user argument; they read identity from config.
3. **No existence oracle.** "Run missing" and "run belongs to someone else" return the same result.
4. **Generated code and generated tests are untrusted.** Both go through the policy gate. Never `exec`/`eval`/import them in the host process.
5. **Policy before execution.** `evaluate_code_policy(code)` parses with `ast` only, never runs anything, and returns `allow` / `needs_approval` / `deny` with reasons. Parse failure → deny.
6. **Sandboxing.** Separate process, temp directory, hard timeout, no network, minimal env (no secrets in env). Timeouts are reported as timeouts.
7. **Approval for risky actions.** File/network access → `needs_approval` → graph `interrupt()`. Nothing runs until a human resumes; reject stops. Approval allows execution only. It never loosens the sandbox.
8. **Run once.** Two keys:
   - **Request key** = hash(user id, masked Request). A Duplicate Request returns the stored Run if it reached a Final outcome.
   - **Execution key** = hash(user id, code, tests). A repeat returns the stored Execution result.
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

## UI principles (Gradio, thin adapter)

- Console output is the primary interface; any UI is a thin adapter over the same graph.
- Show what was decided and by whom: policy verdict + reasons, approval prompt, serving tier, real pytest result.
- Never display unmasked input; echo the masked version.
- Approval is an explicit human action, never a default.
- Errors are honest and specific ("timed out after Ns", "cannot generate now").

## Plans and local material

- All plans go in `plans/`, which is committed so the whole team can read them. Don't create plan or analysis documents elsewhere.
- Name plans `YYYY-MM-DD-NN-slug.md` (NN = two-digit order within the day, e.g. `2026-11-15-03-l1-pipeline.md`), so a sorted listing shows the oldest first and the newest last.
- `plans/TRACKER.md` tracks every phase and item of the hackathon. Update it whenever an item starts or finishes (owner, status, evidence), and link each new plan from its phase.
- `reference/` (hackathon PDFs) and `sample_agent/` (bootcamp notebook) are gitignored local material.
- `docs/` is committed and holds `docs/adr/` (decision records) only.

## Working rules for agents

- **Preserve user changes.** Never discard, overwrite or reformat uncommitted work you didn't create. Check `git status` before destructive operations; stash rather than delete.
- **No secrets.** Never commit keys, `.env` files, or real PII. Read keys from environment variables. Fixtures use obviously fake values.
- **Config files.**
  - `.env.example` is committed and lists every setting with safe sample values.
  - `.env.local` (local runs) and `.env` (deployed) hold real values and are gitignored. Precedence: shell, then `.env.local`, then `.env`.
  - Adding a setting means adding it to `ENV_KEYS` in `config.py` **and** to `.env.example` in the same change; a unit test enforces this.
- **Never read `.env` or `.env.local`.** Agents must not open, `cat`, grep or search them, and must exclude them from broad searches (e.g. `grep -r --exclude='.env*'`). To check that a key is set, test for its presence in the environment without printing it.
- Don't add dependencies, change CI, or push without the user's agreement.
- If context is missing, make the conservative assumption and mark it `UNRESOLVED` rather than guessing silently.

## Open decisions

- Lint/format tooling.
- UNRESOLVED: whether to add the Groq key as a GitHub Actions secret. This enables the soft-case CI job; the user decides.
- Golden-set contents, the judge-like Request set, and the report template (R6 phase).

Decided 2026-11-15 (full list in `plans/2026-11-15-01-problem-statement-alignment.md`):
- **Models:** Groq. One large model (`openai/gpt-oss-120b`) for every step except the handoff summary; the small model (`openai/gpt-oss-20b`) writes the summary and is also the R5 fallback. Model names live in config.
- **Sandbox:** separate process, `python -I`, stripped environment, temp directory, and a network block in Python (audit hook) behind the policy gate. Limits: 10 s timeout (kills the process group), 256 MB memory, first 10 KB of output.
- **Storage:** a SQLite run store (built-in `sqlite3`) for Runs, keys, quota, Tickets and Feedback. The LangGraph checkpointer stays in memory.
- **CI:** hard Golden cases run on every push with a fake model. Soft cases run in a separate job, only when the key secret exists.
- **Code policy, dunders:** dunder names and attributes are no longer denied (`docs/adr/0001-allow-dunder-access-in-code-policy.md`). Known gap: introspection escapes like `().__class__.__bases__[0].__subclasses__()` pass the gate; the sandbox is the remaining defence.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for dipanshuCodes/codeforge, managed via the `gh` CLI. See `agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `agents/domain.md`.
