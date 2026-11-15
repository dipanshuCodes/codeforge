# CodeForge code walkthrough (Level 1)

Audience: contributors who need to understand the code or debug it. Snapshot of the repo at the
Level 1 commit (`be3dff9`). Vocabulary (Request, Run, Execution, Conversation, Serving tier) is
defined in `CONTEXT.md`; rules and invariants are in `AGENTS.md`. Line numbers drift, so search by
function name.

> **L1 status.** Masking (`privacy/masking.py`) is a stub that returns text unchanged. The policy
> gate is a stub (parse failure → `deny`, everything else → `needs_approval`). The sandbox has no
> network block or memory cap yet. Triage and escalation are stubs. These are the R1/R2/R3 work
> items; do not expose the app to anyone but developers.

## 1. The 60-second picture

One LangGraph graph with typed state. Models *propose* (router, requirements, code, tests);
plain Python *decides* (policy, approval, outcome, report).

```
START → ingress → triage → escalation → router ──(kind≠python_function / failure)──┐
                                           │                                        │
                                           ▼                                        │
        requirements → codegen → testgen → policy ──deny──────────────────────────▶ report → END
              │           │         │         ├─allow──────────────▶ execute ──────▶   ▲
              └───────────┴─────────┴──(outcome set)──────────────────────────────────┤
                                              └─needs_approval─▶ approval ─approved─▶ execute
                                                                      └─rejected────────┘
```

Routing rule: after every model node, `state["outcome"]` being set means "stop and go to
`report`". Nothing routes on free text.

Run it: `python -m codeforge` (needs `CODEFORGE_USER_ID`, `CODEFORGE_ROLE`, `GROQ_API_KEY` in the
shell or in `.env.local`).

## 2. Module map

| Module | Role | Pure? |
|---|---|---|
| `config.py` | Settings + the only source of identity | yes (reads env) |
| `privacy/masking.py` | `mask()` at ingress (stub) | yes |
| `agents/*` | One structured model call each; no decisions | no (model) |
| `llm/caller.py` | `StructuredCaller` protocol, Groq + Fake callers, typed errors | no |
| `graph/state.py` | `RunState` TypedDict, `RUN_DEFAULTS` | yes |
| `graph/nodes.py` | The 11 node methods | no |
| `graph/build.py` | Wiring and routing functions | yes |
| `policy/code_policy.py` | `ast`-only code verdicts | yes |
| `sandbox/runner.py` | Subprocess `pytest` with a timeout | I/O |
| `reporting/outcome.py` | Exit code + output → `Outcome` | yes |
| `reporting/report.py` | Template report | yes |
| `runs/store.py` | SQLite store scoped to the config user | I/O |
| `ui/console.py` | Console loop and approval prompt | I/O |

## 3. Request lifecycle, step by step

### 3.1 Entry: `ui/console.py`

`main()` loads env files, builds `Settings`, refuses to start without `GROQ_API_KEY`, builds the
graph with an in-memory checkpointer, then calls `run_console`. `__main__.py` just calls `main()`.

`run_console` is the loop. The part to understand is interrupt handling:

```python
result = graph.invoke({"raw_text": text}, config)       # config carries thread_id
while "__interrupt__" in result:                         # approval node paused the graph
    _show_approval(result["__interrupt__"][0].value, print_fn)
    answer = input_fn(APPROVAL_PROMPT)                   # EOF → "" → rejects
    result = graph.invoke(Command(resume=answer), config)
print_fn(result.get("report") or "")
```

- One console session = one Conversation = one `thread_id` (`uuid4().hex`).
- `_visible()` escapes control characters in model-written text before showing it to the
  Approver, so `\r` or ANSI codes cannot hide lines in the approval view.
- Exit codes: `2` for config errors.

### 3.2 Config: `config.py`

- `load_env_files(dir)` fills `os.environ` from `.env.local` then `.env`. It never overrides a
  value already set (precedence: shell > `.env.local` > `.env`) and skips blank values.
- `load_settings(env)` raises `ConfigError` if `CODEFORGE_USER_ID` is empty or `CODEFORGE_ROLE`
  is not `student`/`instructor`. It fails closed; there is no default identity.
- `Settings` is frozen. Defaults: large model `openai/gpt-oss-120b`, 10 s sandbox timeout, 10 KB
  output cap, `max_repair_attempts = 0`.
- Adding a setting: add it to `ENV_KEYS` and `.env.example` together (a unit test enforces this).

### 3.3 `ingress` node

```python
request = mask(state["raw_text"])
...
self.store.save(RunRecord(run_id=..., conversation_id=..., created_at=..., request=request))
return {**RUN_DEFAULTS, "raw_text": request, "request": request, "run_id": run_id, ...}
```

- Masks first, then saves a stub Run so even a crashed Run is traceable.
- Overwrites `raw_text` with the masked text so the unmasked form is not checkpointed.
- Spreads `RUN_DEFAULTS` so a second Request on the same thread never inherits the previous Run's
  `outcome`, `code`, `verdict` and so on. **If you add a per-Run field to `RunState`, add it to
  `RUN_DEFAULTS` too**, or state will leak between Requests.

### 3.4 `triage` and `escalation`

Stubs: constant calm triage, `escalation: None`. R3 replaces them.

### 3.5 Model nodes and agents

Each agent module is a thin function: build a prompt, call `caller.call(Schema, system, user)`,
return a Pydantic model.

```python
# agents/router.py
def classify(caller, request) -> RouterOutput:
    return caller.call(RouterOutput, SYSTEM, f"Request:\n{request}")
```

Schemas (`agents/schemas.py`): `RouterOutput(kind)`, `Requirements(function_name, description,
params, returns, edge_cases)`, `CodeOutput(code)`, `TestsOutput(tests)`.
`TestsOutput.__test__ = False` stops pytest collecting it as a test class.

The node wrappers in `graph/nodes.py` convert failures into typed state:

| Node | On `ModelOutputError` | On `ModelUnavailableError` | Extra check |
|---|---|---|---|
| `router` | `kind = "other"` → `unsupported` | `cannot_generate` | `kind != python_function` → `unsupported` |
| `requirements` | `cannot_generate` | `cannot_generate` | none |
| `codegen` | `cannot_generate` | `cannot_generate` | `defines_function(code, name)` must be true |
| `testgen` | `cannot_generate` | `cannot_generate` | none |

The router order matters: `except ModelOutputError` comes before `except ModelCallError` because
the first is a subclass of the second.

Testgen is told to write `from solution import <function_name>`. This matches the sandbox, which
saves the code as `solution.py` (`SOLUTION_MODULE`). Change one and you must change the other.

### 3.6 `llm/caller.py`

- `StructuredCaller` is a `Protocol`: `call(schema, system, user) -> schema instance`.
- `GroqCaller` uses `ChatGroq(...).with_structured_output(schema, include_raw=True)` at
  temperature 0. `ValidationError`/`ValueError` → `ModelOutputError`; any other exception →
  `ModelUnavailableError`. The import of `langchain_groq` is lazy so tests need no key.
- `FakeCaller({Schema: instance_or_exception})` is the offline test double. It records `.calls`
  and raises `ModelOutputError` if a schema has no canned response.

### 3.7 `policy` node and `policy/code_policy.py`

```python
decision = strictest(evaluate_code_policy(state["code"]), evaluate_code_policy(state["tests"]))
```

Both generated code and generated tests are checked (invariant 4). `evaluate_code_policy`:

1. Not encodable as UTF-8 → `deny`.
2. Larger than `MAX_SOURCE_BYTES` (100 000) → `deny`.
3. `ast.parse` fails (including `ValueError`, `RecursionError`, `MemoryError`) → `deny`.
4. Otherwise the L1 stub returns `needs_approval`.

`strictest` ranks `allow < needs_approval < deny` and concatenates reasons. R2 replaces step 4
with the real allowlist; keep steps 1-3. The policy never compiles or runs the source.

### 3.8 `approval` node

```python
answer = interrupt({...run_id, verdict, reasons, code, tests...})
approved = isinstance(answer, str) and answer.strip().lower() == "approve"
```

Only the word `approve` counts. Anything else (empty, `yes`, `y`, non-string) rejects with
outcome `rejected`. LangGraph re-runs this node from the top on resume; the code before
`interrupt()` must stay side-effect free.

### 3.9 `execute` node and `sandbox/runner.py`

`run_pytest(code, tests, timeout_s, max_output_bytes)`:

```python
env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp}      # never GROQ_API_KEY
cmd = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", TEST_FILE]
proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdin=DEVNULL, stdout=out,
                        stderr=STDOUT, start_new_session=True)
```

- Writes `solution.py` and `test_solution.py` into a fresh temp dir.
- `start_new_session=True` puts pytest in its own process group; `os.killpg(..., SIGKILL)` runs
  after every Execution (not only on timeout) so stray children do not survive.
- Output goes to a temp file, then only the first `max_output_bytes` are read back.
- Returns `ExecutionResult(exit_code, timed_out, output)`. On timeout `exit_code` is `None`.
- `execute` stores `attempts + 1` so the repair edge can count.

Not yet there (R2): network block, memory cap, Execution key (idempotency).

### 3.10 Outcome: `reporting/outcome.py`

```python
def outcome_from_execution(exit_code, timed_out, output) -> Outcome:
    if timed_out: return "timed_out"
    if exit_code == 0 and at_least_one_test_passed(output): return "tests_passed"
    return "tests_failed"
```

"Tests passed" needs exit 0 **and** a pytest summary showing at least one pass and no
failures/errors. Exit 5 (no tests collected), an all-skipped run and an early `exit(0)` are not
passes. `pytest_summary_line` scans output from the end for lines like `5 passed in 0.04s`.

### 3.11 `report` node and `reporting/report.py`

`report` computes the outcome (`state["outcome"]` if a stage already set one, else from the
execution), renders the template, saves the full `RunRecord`, and returns `outcome` and `report`.

`_headline` maps outcomes to text. Note the `tests_failed` sub-cases: exit 0 →
`NO TEST PASSED`, exit other than 1 → `TESTS DID NOT RUN CLEANLY (pytest exit N)`, else
`TESTS FAILED`. The serving tier line is shown only when code was generated
(`SERVING_TIER = "primary"` in L1). Report text comes only from recorded facts, never model prose.

### 3.12 Run store: `runs/store.py`

- `RunRecord` has no user field on purpose. `RunStore` adds `user_id` from `Settings`.
- `save` is an upsert; the `ON CONFLICT ... WHERE runs.user_id = excluded.user_id` clause means
  one user cannot overwrite another user's Run.
- `get(run_id)` and `list_mine()` both filter by the config user. A missing Run and someone
  else's Run both return `None` (no existence oracle).
- `reasons` is stored as a JSON string; booleans are stored as integers and converted back in
  `_to_record`.
- Adding a column: edit `_FIELDS` (and the integer-column tuple in `_SCHEMA`, and `RunRecord`).
  `CREATE TABLE IF NOT EXISTS` will **not** migrate an existing `codeforge.db`; delete the local
  file or add a migration.

### 3.13 Wiring: `graph/build.py`

- `_continue_or_report(next)` → `"report"` if `outcome` is set, else `next`.
- `_after_policy`: `allow` → execute, `needs_approval` → approval, anything else → report
  (fail closed).
- `_after_approval`: only `approved is True` → execute.
- `after_execute`: the repair edge. It goes back to `codegen` only if the run did not pass and
  `attempts <= max_repair_attempts`. With the L1 default of `0`, `attempts` is already `1`, so it
  always goes to `report`.
- `build_graph(..., run_tests=run_pytest, checkpointer=None)` accepts a fake `run_tests` and a
  fake caller, which is how tests run offline.

## 4. Running and testing

```bash
python -m pytest tests/unit               # fast loop
python -m pytest                           # full suite (gate); `llm`-marked tests need a key
python -m codeforge                        # console
python scripts/trace_pipeline.py "<request>"   # node-by-node trace; rejects at approval so nothing executes
```

Offline graph test skeleton (see `tests/unit/test_graph.py` for the real ones):

```python
caller = FakeCaller({RouterOutput: RouterOutput(kind="python_function"),
                     Requirements: reqs, CodeOutput: CodeOutput(code=code),
                     TestsOutput: TestsOutput(tests=tests)})
graph = build_graph(settings, caller, RunStore(settings), checkpointer=MemorySaver())
result = graph.invoke({"raw_text": "..."}, {"configurable": {"thread_id": "t1"}})
```

## 5. Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| `Config error: CODEFORGE_USER_ID is not set` | Env var missing, or `.env.local` not in the current directory (`load_env_files(Path.cwd())`) | `config.py`, `ui/console.py:main` |
| `Config error: GROQ_API_KEY is not set` | Key not in the shell or `.env.local` | `main()`. Check presence only; do not print or open `.env*` |
| Report says `CANNOT GENERATE NOW` | Provider failure, bad structured output, or generated code lacks a top-level function named `requirements.function_name` | Use `scripts/trace_pipeline.py` to see which node and which error type. `codegen` also fails when the model wraps the function in a class |
| Report says `NOT SUPPORTED` for a valid Python request | Router answered `other`, or its output failed to parse (parse failure maps to `other`) | `nodes.router`, `agents/router.py` prompt |
| Every Run waits for approval | Expected in L1: policy stub returns `needs_approval` | `policy/code_policy.py` `_L1_STUB_DECISION` |
| Approval typed but run says `REJECTED` | Only the exact word `approve` (case-insensitive, trimmed) counts | `nodes.approval` |
| `TESTS DID NOT RUN CLEANLY (pytest exit 5)` | No tests collected: model wrote no `test_` functions | testgen prompt, `Output` section of the report |
| Exit 2/4 or `ModuleNotFoundError: solution` / `ImportError` | Generated tests import a different module or function name than `solution` / `function_name` | `agents/testgen.py`, `sandbox/runner.py` `SOLUTION_MODULE` |
| `No module named pytest` in the sandbox output | The interpreter running CodeForge lacks pytest (the sandbox uses `sys.executable`) | `pip install -e .` in the same venv |
| `TIMED OUT after 10s` | Infinite loop or slow code; the process group was killed | `Settings.sandbox_timeout_s` |
| Output looks truncated | Capped at `max_output_bytes` (10 KB) | `Settings.max_output_bytes` |
| New Request shows the previous Run's outcome/code | A new `RunState` field is missing from `RUN_DEFAULTS` | `graph/state.py` |
| `sqlite3.OperationalError: no column named ...` | Local DB created with an older schema | Delete the local `codeforge.db` or migrate |
| `get(run_id)` returns `None` for a Run you know exists | It belongs to a different `CODEFORGE_USER_ID`. This is by design | `runs/store.py` |
| Graph does not stop at approval in a test | No checkpointer passed; `interrupt()` needs one | `build_graph(..., checkpointer=MemorySaver())` |
| Resuming does nothing / starts a new Run | Different `thread_id` between invoke and resume | `run_console` reuses one `config` |

Debugging order that works: reproduce with `FakeCaller` offline → check `result["outcome"]` and
`result["verdict"]` (routing reads only typed fields) → read the stored Run via
`RunStore.get(run_id)` (it has code, tests, output, exit code, tier) → only then involve the model.

## 6. Rules to keep when changing code

- Agents return Pydantic models and never decide; decisions live in `policy/`, `reporting/`,
  `graph/`.
- Route on typed fields (`kind`, `verdict`, `approved`, `outcome`). Never on text.
- Never `exec`, `eval` or import generated code in the host process.
- Never weaken a security invariant or a hard golden case to make a test pass.
- Rule changes are test-first (`tests/unit/test_<module>.py`), and `python -m pytest` must exit 0
  before you call a change done.
- Keep `ingress` as the first node to touch text, and keep identity in `config.py`.

## 7. Known gaps (by design in L1)

| Gap | Phase |
|---|---|
| `mask()` returns text unchanged | R1 |
| Allowlist policy, network block, memory cap, Request/Execution keys, quota | R2 |
| Triage, escalation rules, tickets, handoff | R3 |
| Retry, circuit breaker, fallback model, real `SERVING_TIER` | R5 |
| Repair attempts (`max_repair_attempts = 0`) | after R1/R2/R6 |
| Golden set and CI gate (`evals/`, `.github/workflows/ci.yml`) | R6 |
