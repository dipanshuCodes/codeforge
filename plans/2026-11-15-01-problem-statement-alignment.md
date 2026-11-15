# CodeForge: agreed problem statement

Status: agreed in the grilling session, 2026-11-15. The vocabulary is in `CONTEXT.md`. The
summary of the original brief is in `reference/problem-statement.md`.
Submission: **2026-11-15, 3:30 PM IST**.

## 1. Problem we are solving

Students on a course platform need working Python code for small, well-scoped tasks, often
under deadline pressure. They also need to know whether it really works. An LLM alone writes
plausible code, claims it works, and will run whatever it is asked to. CodeForge turns a
plain-English Request into code and pytest tests, runs them in a locked sandbox, and reports
the **real** result. Throughout, it protects the student's secrets, refuses dangerous work,
hands distressed students to a human, and keeps answering when the model provider fails.

**Principle:** the model supplies judgement; plain, unit-tested Python makes every decision.

## 2. Target users and pain points

| Who | Pain point | What CodeForge does |
|---|---|---|
| **Student** (User, role `student`) | Needs correct code fast; can't tell whether it works | Code + tests, run for real; an honest report |
| Student who pastes secrets or personal data | Keys and Aadhaar numbers leak into prompts and logs | Masking at ingress, before anything else |
| Student asking for something destructive | Could harm the host or other users | The policy gate denies it, and nothing runs |
| Frustrated or urgent student | Stuck, wants a person | Escalation in code, a P1 Ticket, and a Handoff note |
| **Approver** (any human at the console or UI) | Must vet risky code before it runs | The graph pauses; nothing runs until they approve |
| **Instructor** (role `instructor`) | Needs isolation guarantees and visibility | Identity only from config; Runs scoped to their owner |
| Platform operator | Provider outages, cost | Retries, fallback, Template tier, quotas |

## 3. Desired outcome

At 11:47 PM, all four scene actors are handled correctly. Each outcome is shown live and backed
by a passing Golden case:

- **Student A** (palindrome): code and tests, tests passed in the sandbox.
- **Student B** (delete home folder): denied by the policy gate; nothing runs.
- **Student C** (key + Aadhaar + "get me a human"): masked everywhere; a P1 Ticket containing no secrets.
- **Provider returning 429s**: every Request still gets an answer, and the report names the Serving tier.

## 4. Scope

| Item | Decision |
|---|---|
| Level 1 pipeline | **In** (being built first) |
| R1 Identity and privacy | **In** |
| R2 Safe execution | **In** |
| R6 Evals as a gate | **In** |
| R3 Escalation and handoff | **In** (chosen lever) |
| R5 Resilience | **In** (chosen lever) |
| R4 Cost and latency | Only if time remains; model names in config keep the door open |
| Gradio UI | **In**, owned by Neha, thin adapter; drop if not working by **1:30 PM IST** |
| R7 Safe SQL | **Out** (no sample database; second policy surface) |

### Decisions

**Requests and Runs**
- **Duplicate Requests:** request-level deduplication on the Request key, hash(user, masked text). It returns the stored Run only if that Run has a Final outcome; a Run awaiting approval is resumed. Transient failures are processed again.
- **Execution key:** the brief's hash(user, code, tests), checked right before the sandbox. It guards against graph replays and Repair attempts that return unchanged code.
- **Conversation:** maps to a LangGraph `thread_id`. Escalation signals accumulate across it.
- **Repair loop:** up to 2 Repair attempts, so 1–3 Executions per Run. Repair 1 may change the code only. Repair 2 may also change the tests, but a rule rejects any repair that reduces the number of tests or assertions. Two failed repairs lead to Escalation (P3).
- **Unsupported Requests** (`other`, and `sql_query` while R7 is out): an honest "not supported" report and no code.

**Identity, quota and storage**
- **Approver:** any human at the console or UI. Approval is not role-gated. In production we would gate it on the instructor role from a separate process.
- **Run quota:** every submitted Request counts, Duplicate Requests included, except Transient failures. The limit is set per config: R1 demo User 5, chaos-run User 25. The window resets daily.
- **Storage:** Runs, keys, quota, Tickets and Feedback live in SQLite (built-in `sqlite3`), and every query is filtered by the config User. The LangGraph checkpointer stays in memory, because approval happens in the same process.

**Policy and sandbox**
- **Policy gate:** an allowlist, applied to both the code and the tests.
  - **allow:** pure standard-library modules, plus pytest and the generated module.
  - **needs_approval:** file access (`open`, `pathlib`) and network access (`socket`, `urllib`, `http`, `requests`).
  - **deny:** `os`, `sys`, `subprocess`, `shutil`, `ctypes`, `importlib`, `builtins`, `eval`/`exec`/`compile`/`__import__`, dunder attribute access, parse failures, and **anything not listed**.
- **Approval** allows execution only. The sandbox stays locked (no network; files only inside the temp directory).
- **Sandbox:** separate process, `python -I`, stripped environment, temp directory, and a network block in Python (audit hook) behind the policy gate. Limits, all in config: 10 s timeout (the whole process group is killed), 256 MB memory, first 10 KB of output. A timeout is reported as a timeout and is a Final outcome.

**Masking, escalation and serving**
- **Masking:** applied at ingress, in this order.
  - `[SECRET]`: `sk-…`, `gsk_…` (16+ characters)
  - `[EMAIL]`
  - `[CARD]`: 13–19 digits that pass the Luhn check
  - `[AADHAAR]`: 12 digits starting 2–9, no checksum, so it fails closed
  - `[PHONE]`: 10 digits starting 6–9, optional `+91`/`0`

  Must not be masked: `2432902008176640000`, `1234567890`, `2024`, `fibonacci(30)`.
- **Triage** returns language, sentiment (`calm` / `mildly_unhappy` / `angry`), urgency (`low` / `high`) and `wants_human`. It does **not** return the task type; the Router alone decides the Request kind.
- **Escalation rules**, first match wins:

  | Rule | Priority | SLA |
  |---|---|---|
  | `wants_human` and (angry or high urgency) | P1 | 1 h |
  | angry, or `wants_human` alone | P2 | 4 h |
  | 2+ `mildly_unhappy` turns | P3 | 24 h |
  | 2+ policy denials | P3 | 24 h |
  | second failed Repair attempt | P3 | 24 h |

  Only P1 skips generation.
- **Handoff note:** a template summary line in code (always present), an advisory AI summary from the small model (re-masked, absent during an outage), the masked Request, the attempts, and the last failing test.
- **Models:** Groq. One large model for every step except the AI summary, which uses the small model. The small model is also the R5 fallback. Model names live in config. Check the key's model access before building the model factory.
- **Chaos switch:** injects a mix of 429, 503, timeouts and bad output into 60% of model calls, with a fixed random seed. Only transient errors are retried; bad output goes straight to the fallback.
- **Template tier:** strict keyword rules with required and blocking words. Exactly one match is required; otherwise "cannot generate now" plus a Ticket. Look-alike Requests get unit tests.

**Evals and feedback**
- **Evals in CI:** hard Golden cases run on every push with a fake model and no key. Soft cases run in a separate job only when the Groq key secret exists, and fail below 85%.
- **Feedback flywheel:** `/bad` in the console or 👎 in the UI creates Feedback. `codeforge feedback promote <id>` writes a draft Golden case. A human writes the expected outcome and Reference test. Then red, then green.

## 5. Constraints

- Python 3.11+, LangGraph, LangChain, pytest, and the shared Groq key. No new dependencies or CI changes without agreement.
- Agents are separate graph nodes. Business rules are plain Python with unit tests.
- Build order: Level 1 → R1, R2, R6 → R3, R5 → Gradio → (R4).
- Team of 3, not the 4 the brief assumes:
  - **Dipanshu:** graph design and Level 1 pipeline, working alone at first.
  - **Siyahul:** joins for evals and policies (R1, R2, R6), then R3 and R5.
  - **Neha:** Gradio UI and the presentation.
- Level 1 is built with every node in place from day one (ingress, triage, escalation, router, requirements, codegen, testgen, policy, execute, report). Stubs return safe defaults; `execute` is a real subprocess with a timeout from the start.

## 6. Success criteria

1. Every pass condition for Level 1, R1, R2, R3, R5 and R6 is demonstrable live from the console (see `reference/problem-statement.md`).
2. `python -m pytest` exits 0 on main, and CI is green. Hard Golden cases pass 100%; soft cases pass at least 85%.
3. **Our own bar:** at least 90% of 10–15 judge-like Requests pass our hidden Reference tests.
4. Deliverables are complete: README with a flowchart, team split and three defended decisions; `golden_set.json` with gate output; chaos-run log; a ~10-minute incident-led presentation in which everyone speaks.

## 7. Assumptions and open questions

- ~~**UNRESOLVED:** which Groq models the shared key can access.~~ Resolved 2026-11-15: large
  `openai/gpt-oss-120b`, small `openai/gpt-oss-20b`.
- **UNRESOLVED:** who adds the Groq key as a GitHub Actions secret (the user decides; agents don't touch CI or secrets).
- **Assumption:** the judges' hidden requests are small, single-function Python tasks like the examples in the brief.
- **Assumption:** a network block in Python plus the policy gate is acceptable sandboxing for the hackathon. OS-level isolation (Docker `--network none`) is noted as the production step.
- **Not yet designed:** the golden-set contents, the judge-like Request set, and the exact report template. These are for the R6 phase with Siyahul.
