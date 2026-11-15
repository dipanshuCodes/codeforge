# R2 Safe execution

Issue: dipanshuCodes/codeforge#5 · Owner: Siyahul · Branch: `feat/r2-safe-execution` (stacked on R1)

## What changes

- **Policy allowlist** (`policy/code_policy.py`, `ast` only), on both code and tests. allow:
  pure stdlib modules (listed in `ALLOWED_MODULES`), `pytest`, `solution`. needs_approval:
  `open`, `pathlib`, `io`, `socket`, `urllib`, `http`, `requests`. deny: everything else,
  including `os`, `sys`, `subprocess`, `shutil`, `ctypes`, `importlib`, `builtins`,
  `eval`/`exec`/`compile`/`__import__`/`globals`/`locals`/`vars`/`breakpoint`, dunder names
  and attributes (except `__name__`), `getattr`/`setattr`/`delattr` with a computed or dunder
  name, relative imports. A nesting limit (100) denies pathological source on every Python
  version. Pure code is now `allow` and runs without approval.
- **Sandbox lockdown** (`sandbox/runner.py`): the child runs a bootstrap that adds an audit
  hook before pytest starts. It blocks sockets, process spawning (a child would escape the
  network block) and writes outside the temp dir (`/dev/null` allowed). `-B` stops `.pyc`
  writes; `TMPDIR` points pytest's `tmp_path` inside the temp dir.
- **Memory cap**: `RLIMIT_AS` = 256 MB (`Settings.sandbox_memory_bytes`). Linux fails closed if
  it can't be set (exit 3). macOS refuses the limit ("current limit exceeds maximum"), so it is
  skipped there and the timeout is the backstop.
- **Request key** = sha256(user, masked Request). A Duplicate Request whose earlier Run has a
  Final outcome gets a new Run row copying it (`duplicate_of`), with "Duplicate Request: same
  as Run …" on top of the stored report; nothing is generated or run. It still counts toward
  the quota (checked first).
- **Execution key** = sha256(user, code, tests), checked in `execute`. A repeat reuses the
  stored result; the report says "Execution reused".

## Assumptions

- Runs awaiting approval are not resumed across Conversations. The checkpointer is in memory,
  so a Run left pending by a closed console cannot be resumed; it is processed again. The
  console blocks on approval, so a live pending Run can't be duplicated there. UNRESOLVED for
  the Gradio UI.
- `rejected` is a Final outcome (CONTEXT.md), so resubmitting a rejected Request returns the
  rejection. Change the wording to get a fresh Run.
- The memory cap is untested on Linux here (Docker daemon not running); CI will exercise it.
- Golden cases move into `evals/golden_set.json` with R6; graph tests cover them now.
