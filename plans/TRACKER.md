# CodeForge hackathon tracker

The one place to see what is done and what is left. **Submission: 2026-11-15, 3:30 PM IST.**

How to use it:
- Each open phase has a GitHub issue (linked in the Overview table) with the checklist and how to pick it up.
- Before starting an item, put your name in **Owner** and set Status to `in progress`.
- When it is done, set Status to `done`, fill **Evidence** (test command + exit code, commit,
  or transcript location) and the time. "Done" means the check in the Evidence column passes.
- A blocked item gets `blocked` and one line saying what it waits for.
- Status values: `todo` · `in progress` · `blocked` · `done` · `dropped`.
- Plans live next to this file as `YYYY-MM-DD-NN-slug.md` (NN = order within the day), so they
  sort oldest first and the newest is at the bottom. Link the plan from its phase below.

Last updated: 2026-11-15 by Claude for Dipanshu.

## Where we are: the system today

The graph as wired in `src/codeforge/graph/build.py`. Colour shows how real each part is.
Dashed boxes and edges don't exist in code yet. Recolour a box when its phase item is done.

```mermaid
flowchart TD
    START([Console: python -m codeforge]) --> ingress

    ingress["<b>ingress</b><br/>mask secrets/PII first · R1<br/>config identity, new Run, reset fields"]:::built
    quota["Run quota · R1<br/>per User per UTC day, before any model call"]:::built
    reqkey["Request key lookup · R2<br/>Duplicate → stored Run"]:::built
    triage["<b>triage</b><br/>fixed: calm / low / no human · R3"]:::stub
    escalation["<b>escalation</b><br/>always none · R3"]:::stub
    ticket["Ticket + Handoff note · R3"]:::todo
    router["<b>router</b> · model<br/>python_function / sql_query / other"]:::built
    requirements["<b>requirements</b> · model"]:::built
    codegen["<b>codegen</b> · model"]:::built
    testgen["<b>testgen</b> · model"]:::built
    resilience["retry / breaker / fallback /<br/>template tier · R5"]:::built
    policy["<b>policy</b> · ast allowlist · R2<br/>code + tests"]:::built
    approval{{"<b>approval</b><br/>interrupt · only 'approve' approves"}}:::built
    execute["<b>execute</b> · sandbox<br/>python -I, 10 s, group kill, env strip, 10 KB<br/>audit hook: no net/spawn/outside writes<br/>256 MB (Linux), Execution key · R2"]:::built
    repair{"<b>repair</b> · model + rules<br/>max 2 · repair 1 code only<br/>fewer tests or assertions rejected"}:::built
    report["<b>report</b><br/>template from real pytest exit<br/>saved to SQLite runs table"]:::built
    DONE([Console prints report])
    ui["Gradio UI · Neha"]:::todo
    gate["Golden gate + CI · R6"]:::todo

    ingress --> quota --> triage --> escalation --> router
    quota -- "over limit → quota_exceeded" --> report
    quota -.-> reqkey -.-> triage
    escalation -. "P1 · R3" .-> ticket -.-> DONE
    router -- "sql_query / other" --> report
    router -- python_function --> requirements --> codegen --> testgen --> policy
    requirements & codegen & testgen -- "bad output → cannot_generate" --> report
    codegen -.- resilience
    policy -- deny --> report
    policy -- needs_approval --> approval
    policy -- "allow (no rule yields it yet)" --> execute
    approval -- reject --> report
    approval -- approve --> execute --> repair
    repair -- "proposed: gate again" --> policy
    repair -- no --> report --> DONE
    ui -.-> START
    gate -.- report

    class ingress stub
    classDef built fill:#d3f2d3,stroke:#2e7d32,color:#000
    classDef stub fill:#fff1c2,stroke:#b8860b,color:#000
    classDef todo fill:#eeeeee,stroke:#888,stroke-dasharray:5 5,color:#555
```

Legend: **green** = built and unit-tested · **amber** = exists, but a stub or partial (the later
phase is named in the box) · **grey dashed** = not built yet.

Right now: every L1 node runs end to end offline (94 unit tests green). Not yet checked live
against Groq. Next: L1 live check and commit, then R1 / R2 / R6.

## Cases by node: covered vs pending

`[x]` = built and covered by a unit test · `[ ]` = pending (phase in brackets). "Covered" means
offline unit tests only; nothing here is checked live against Groq yet.

**ingress**
- [x] User id and role come from config only
- [x] New Run created and saved before approval; a second Request on the same thread starts clean
- [ ] Mask `[SECRET]`, `[EMAIL]`, `[CARD]`, `[AADHAAR]`, `[PHONE]` (currently pass-through) [R1]
- [ ] Must-not-mask numbers (`2432902008176640000`, `1234567890`, `2024`) [R1]
- [ ] "I'm an instructor" changes nothing [R1]
- [ ] Run quota per user, enforced before generation [R1]
- [ ] Duplicate Request returns the stored Run (Request key) [R2]

**triage**
- [ ] Model call for language, sentiment, urgency, wants_human (now fixed: calm / low / no human) [R3]

**escalation**
- [ ] P1 (angry, or asks for a human) → Ticket, skips generation [R3]
- [ ] P2/P3 → Ticket, then continue [R3]
- [ ] Two mildly unhappy turns escalate [R3]
- [ ] Calm Request opens no Ticket [R3]
- [ ] Handoff note with no key or Aadhaar [R3]

**router**
- [x] `python_function` goes on to requirements
- [x] `sql_query` → "not supported" report, no code
- [x] Bad router output → `other` → "not supported"
- [x] Model outage → "cannot generate now"

**requirements / codegen / testgen**
- [x] Happy path (palindrome example)
- [x] Bad model output → "cannot generate now"
- [x] Generated code missing the required function name → "cannot generate now"
- [x] Tests import from the solution module
- [x] Retry, circuit breaker, small-model fallback, template tier [R5]
- [x] Chaos switch: 20 of 20 Requests answered at 60% failures [R5]

**policy**
- [x] Parse failure, null byte, lone surrogate, oversized or deeply nested source → deny
- [x] Unparsable tests → denied without asking for approval
- [x] Any other valid code → needs_approval (stub)
- [ ] Allowlist: deny `os`, `sys`, `subprocess`, `shutil`, `ctypes`, `importlib`, `builtins`, `eval`/`exec`/`compile`/`__import__`, dunders [R2]
- [ ] Safe code → `allow` (no rule yields it yet) [R2]
- [ ] Destructive Request ("delete my home folder", Student B) → denied, nothing runs [R2]
- [ ] Weakening one rule turns the gate red and names the case [R6]

**approval**
- [x] Only an exact "approve" approves (case and spaces ignored)
- [x] Anything else, including empty, rejects; reject runs nothing
- [x] Degraded tier never auto-approves risky code [R5]

**execute (sandbox)**
- [x] Passing tests (exit 0), failing tests (exit 1), no tests (exit 5)
- [x] `while True: pass` killed at the timeout and reported as a timeout
- [x] Whole process group killed
- [x] Env stripped (no Groq key); output cut to 10 KB; non-UTF-8 safe; temp dir removed
- [ ] Network block [R2]
- [ ] 256 MB memory cap (check macOS vs Linux CI) [R2]
- [ ] Same code + tests runs once (Execution key) [R2]

**repair**
- [x] Edge exists; with max attempts = 0 a failing Run ends in "tests failed"
- [x] Repair 1 changes code only; repair 2 may change tests
- [x] A repair may not reduce tests or assertions (a shrunken `parametrize` list is a known gap)
- [x] Policy gate runs again after each repair
- [x] Two failed repairs → P3 Ticket (minimal row; R3 enriches it)
- [ ] Golden cases for repair [R6]

**report**
- [x] Passed, failed (with output), exit 5, timeout, denied, rejected, unsupported, cannot_generate
- [x] "Tests passed" only on exit 0 with a real passing test; all-skipped is never a pass
- [x] Run saved to SQLite; one user cannot read another's Run (missing = not yours)
- [x] Report names the Serving tier from the resilience layer [R5]

**Cross-cutting**
- [ ] Live Groq smoke test and the two live checks (L1 example, Student B) [L1]
- [ ] `evals/golden_set.json`: ≥20 cases, hard 100%, soft ≥85% [R6]
- [ ] Hidden reference tests, CI gate, feedback flywheel [R6]
- [ ] Gradio UI [Neha]

## Overview

| # | Phase | Owner | Status | Plan |
|---|---|---|---|---|
| 1 | Brainstorm and scope | Dipanshu | done | [01 problem statement](2026-11-15-01-problem-statement-alignment.md) |
| 2 | Level 1 pipeline | Dipanshu | in progress (code + unit tests done; live check open) | [02 node actions](2026-11-15-02-l1-node-actions.md), [03 L1 plan](2026-11-15-03-l1-pipeline.md), issue [#3](https://github.com/dipanshuCodes/codeforge/issues/3) |
| 3a | R1 Identity and privacy | Siyahul | todo | issue [#4](https://github.com/dipanshuCodes/codeforge/issues/4) |
| 3b | R2 Safe execution | Siyahul | in progress | [plan](2026-11-15-05-r2-safe-execution.md) · branch `feat/r2-safe-execution` |
| 3c | R6 Evals as a gate | Siyahul | todo | issue [#6](https://github.com/dipanshuCodes/codeforge/issues/6) |
| 3d | Repair loop (after R1/R2/R6 green) | Dipanshu | in progress | issue [#7](https://github.com/dipanshuCodes/codeforge/issues/7) |
| 4a | R3 Escalation and handoff | Siyahul | todo | issue [#8](https://github.com/dipanshuCodes/codeforge/issues/8) |
| 4b | R5 Resilience | Siyahul | done (code + unit tests; live Groq check open) | issue [#9](https://github.com/dipanshuCodes/codeforge/issues/9) |
| 4c | Gradio UI (drop if not working by **1:30 PM IST**) | Neha | todo | issue [#10](https://github.com/dipanshuCodes/codeforge/issues/10) |
| 4d | R4 Cost and latency (only if time remains) | — | todo | issue [#11](https://github.com/dipanshuCodes/codeforge/issues/11) |
| 5 | Deliverables and presentation | Neha + all | todo | issue [#12](https://github.com/dipanshuCodes/codeforge/issues/12) |
| — | R7 Safe SQL agent | — | dropped (out of scope) | — |

Order: 2 → 3a/3b/3c → 3d → 4a/4b → 4c → 4d. Don't start a later phase while Level 1 or the gate is red.

## 1. Brainstorm and scope — done

| Item | Status | Evidence |
|---|---|---|
| Agreed problem statement, scope and decisions | done | `plans/2026-11-15-01-problem-statement-alignment.md` |
| Domain vocabulary | done | `CONTEXT.md` |
| Shared agent rules | done | `AGENTS.md`, `CLAUDE.md` (commit 78978d3) |
| Groq model access checked (120b large, 20b small) | done | `plans/2026-11-15-01-problem-statement-alignment.md` §7 |
| Seven L1 node decisions | done | `plans/2026-11-15-02-l1-node-actions.md` |

## 2. Level 1 pipeline — Dipanshu

Plan: [2026-11-15-03-l1-pipeline.md](2026-11-15-03-l1-pipeline.md).

| Task | Item | Status | Evidence |
|---|---|---|---|
| 0 | Project skeleton, config-only identity | done | `tests/unit/test_config.py` passes |
| 1 | Policy stub (parse fail → deny, else needs_approval) | done | `tests/unit/test_code_policy.py` passes |
| 2 | Outcome from pytest exit code + template report | done | `tests/unit/test_outcome.py`, `test_report.py` pass |
| 3 | SQLite run store scoped to config user | done | `tests/unit/test_run_store.py` passes |
| 4 | Subprocess sandbox (timeout, group kill, stripped env, 10 KB) | done | `tests/unit/test_sandbox.py` passes |
| 5 | Model caller + four agents | done (offline) | `tests/unit/test_agents.py` passes |
| 5 | Groq smoke test (`python -m pytest -m llm -v`) | todo | skipped: `GROQ_API_KEY` not set in the shell. Record the structured-output method that works in plan 02 |
| 6 | LangGraph graph, every node, approval interrupt | done | `tests/unit/test_graph.py` passes |
| 7 | Console entry point + README | done | `tests/unit/test_console.py` passes |
| 7 | Live check: L1 pass-condition Request → approve → result | todo | needs the key; record transcript in plan 02 |
| 7 | Live check: Student B "delete my home folder" → reject → nothing runs | todo | record transcript in plan 02 |
| — | Full suite green | done | `python -m pytest` → 94 passed, 1 skipped, exit 0 (2026-11-15) |
| — | Commit the L1 work | done | commit "feat: Level 1 pipeline…" on `docs/problem-statement-alignment` (not pushed) |

## 3a. R1 Identity and privacy — Siyahul

| Item | Status | Evidence |
|---|---|---|
| Masking at ingress in order: `[SECRET]` (`sk-…`, `gsk_…`, 16+), `[EMAIL]`, `[CARD]` (Luhn), `[AADHAAR]`, `[PHONE]` | done | `privacy/masking.py`; `tests/unit/test_masking.py` |
| One unit test per mask, plus must-not-mask: `2432902008176640000`, `1234567890`, `2024`, `fibonacci(30)` | done | `tests/unit/test_masking.py` (25 cases) |
| Masked text everywhere: prompts, logs, run records, UI echo | done (no log lines exist yet; console echoes `request`, which is masked) | `test_ingress_r1.py::test_pasted_key_and_aadhaar_are_masked_in_prompts_run_and_db` (checks the SQLite file bytes) |
| Run quota per user, enforced before generation | done (golden case → R6) | `policy/quota.py`, `CODEFORGE_RUN_QUOTA`; `test_quota.py`, `test_ingress_r1.py::test_quota_refuses_before_any_model_call` |
| "I'm an instructor" in a message changes nothing | done (golden case → R6) | `test_ingress_r1.py::test_identity_claims_in_the_message_change_nothing` |
| User A can't read user B's runs; missing = not yours | done; graph-level test added, golden case → R6 | `test_run_store.py`, `test_ingress_r1.py::test_user_b_cannot_read_user_a_run_and_missing_looks_the_same` |
| README warning ("developers only until R1/R2") removed once R1 + R2 are done | todo | |

## 3b. R2 Safe execution — Siyahul

| Item | Status | Evidence |
|---|---|---|
| Policy allowlist replaces the "everything else needs approval" stub (deny `os`, `sys`, `subprocess`, `shutil`, `ctypes`, `importlib`, `builtins`, `eval`/`exec`/`compile`/`__import__`, dunders, anything not listed) | done | `policy/code_policy.py`; `tests/unit/test_code_policy.py` |
| Destructive request (Student B) → DENIED, nothing runs | done (golden case → R6) | `test_code_policy.py::test_student_b_delete_home_folder_is_denied`, `test_graph.py::test_denied_code_runs_nothing` |
| Network block in the sandbox (audit hook) | done; also blocks spawning and writes outside the temp dir | `test_sandbox.py` |
| 256 MB memory cap (check `RLIMIT_AS` on macOS vs Linux CI) | done on Linux (untested locally); macOS cannot enforce it | `test_sandbox.py::test_memory_cap` (skipped on macOS) |
| Request key: duplicate Request returns the stored final Run | done | `test_idempotency.py`, `test_run_store.py` |
| Execution key: same code + tests runs once | done | `test_idempotency.py::test_same_code_and_tests_execute_once` |
| `while True: pass` killed at the timeout and reported as a timeout | done in L1 sandbox; golden case todo | `test_sandbox.py` |
| Nothing runs until an approver resumes | done in L1 graph; golden case todo | `test_graph.py` |

## 3c. R6 Evals as a gate — Siyahul

| Item | Status | Evidence |
|---|---|---|
| `evals/golden_set.json`: ≥20 cases, ≥10 hard, ≥10 soft | todo | |
| `tests/test_golden_gate.py`: hard 100%, soft ≥85% | todo | |
| Hidden reference tests in `evals/reference_tests/` | todo | |
| Judge-like Request set (10–15); our bar ≥90% pass hidden reference tests | todo | |
| CI: hard cases on every push with a fake model | todo | needs agreement before touching CI |
| CI: soft-case job only when the Groq secret exists | blocked | UNRESOLVED: who adds the secret |
| Demo: weakening a rule (allow `import os`) turns the gate red and names the case; restoring turns it green | todo | |
| Feedback flywheel: `/bad` → Feedback → `codeforge feedback promote <id>` → red, then green | todo | |

## 3d. Repair loop — after R1/R2/R6 are green

Plan: [2026-11-15-07-repair-loop.md](2026-11-15-07-repair-loop.md) (in progress on branch `feat/repair-loop`; R6 golden cases still pending).

| Item | Status | Evidence |
|---|---|---|
| `max_repair_attempts` 0 → 2 | done | `test_config.py::test_loads_identity_from_env` |
| Repair 1 changes code only; repair 2 may change tests | done | `test_repair_rules.py`, `test_graph_repair.py` |
| Rule: a repair may not reduce tests or assertions | done | `test_repair_rules.py`, `test_graph_repair.py::test_repair_that_deletes_a_failing_test_is_rejected_and_counted` |
| Policy gate runs again after each repair | done | `test_graph_repair.py::test_repaired_code_goes_through_the_policy_gate_again` |
| Execution key guards an unchanged repair | done | rule rejects it first (`test_unchanged_code_is_rejected`); `execute` still replays via the key |
| Two failed repairs → P3 Ticket | done (minimal; R3 owns Tickets) | `test_graph_repair.py::test_two_failed_repairs_report_the_real_failure_and_open_a_p3_ticket` |
| Golden cases | todo | blocked on R6 (#6) |

## 4a. R3 Escalation and handoff — Siyahul

| Item | Status | Evidence |
|---|---|---|
| Triage model call (language, sentiment, urgency, wants_human) | todo | |
| Escalation rules P1/P2/P3 in code, with unit tests | todo | |
| Tickets table + Handoff note (template line + advisory small-model summary, re-masked) | todo | |
| Student C → P1 Ticket with no key or Aadhaar; P1 skips generation | todo | |
| A calm Request opens no Ticket | todo | |
| Two mildly unhappy turns in one Conversation escalate | todo | |

## 4b. R5 Resilience — Siyahul

| Item | Status | Evidence |
|---|---|---|
| Model-call wrapper: jittered retry on transient errors only, circuit breaker | done | `llm/resilient.py`, `policy/resilience.py`; `test_resilience_rules.py`, `test_resilient_caller.py` |
| Fallback to the small model | done | `llm/factory.py`; `test_resilient_caller.py` |
| Template tier: strict keyword rules, exactly one match, else "cannot generate now" + Ticket | done | `policy/templates.py`; `test_templates.py`; ticket is a minimal store row (R3 #8 enriches) |
| Chaos switch: 60% failures, fixed seed | done | `llm/chaos.py`, `CODEFORGE_CHAOS_RATE/SEED`; `test_resilient_caller.py`, `test_config.py` |
| 20 of 20 Requests answered under chaos; report names the Serving tier | done | `test_chaos_run.py`; `scripts/chaos_run.py` → 20/20 |
| Total outage: template tasks still work; unknown task → honest refusal + Ticket | done | `test_resilient_graph.py` |
| Degraded tier never auto-approves risky code | done | `test_resilience_rules.py`, `test_resilient_graph.py` |
| Chaos-run log saved for the submission | done | `evals/chaos_run_log.txt` |

## 4c. Gradio UI — Neha (drop at 1:30 PM IST if not working)

| Item | Status | Evidence |
|---|---|---|
| Thin adapter over the same graph; no logic the console can't reach | todo | |
| Shows masked echo, verdict + reasons, approval prompt, Serving tier, real pytest result | todo | |
| Approve and deny paths exercised by hand | todo | |
| 👎 creates Feedback | todo | |

## 4d. R4 Cost and latency — only if time remains

| Item | Status | Evidence |
|---|---|---|
| (Not designed. Model names in config keep the door open.) | todo | |

## 5. Deliverables and presentation

| Item | Owner | Status | Evidence |
|---|---|---|---|
| README: setup, flowchart, team split, three defended decisions | — | todo | |
| `golden_set.json` with gate output | Siyahul | todo | |
| Chaos-run log | Siyahul | todo | |
| ~10-minute incident-led presentation; everyone speaks | Neha | todo | |
| Live demo of the four scene actors (Students A, B, C; provider 429s) | all | todo | |
| `python -m pytest` exits 0 on main, CI green | all | todo | |
| Submit by 3:30 PM IST | Dipanshu | todo | |

## Open items

- UNRESOLVED: who adds the Groq key as a GitHub Actions secret (issue [#13](https://github.com/dipanshuCodes/codeforge/issues/13)).
- ~~Are plans committed?~~ Decided 2026-11-15: yes. `plans/` (and this tracker) are committed;
  `AGENTS.md` and `CLAUDE.md` say so.
