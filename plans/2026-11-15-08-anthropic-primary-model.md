# Model chain: Sonnet → Groq 120b → Haiku → templates

Status: IMPLEMENTED 2026-11-15 (offline; live checks with real keys still open, step 9). Dependency approved by user.

## Decided by the user
- Tier order: **1st `claude-sonnet-5-5`**, **2nd Groq `openai/gpt-oss-120b`**, **3rd `claude-haiku-5-5`** (last model fallback).
- Then the existing **template tier** (R5 outage path). Missing keys must reach it, not crash.
- Missing Anthropic key is tolerated (runs on what is available).

## What exists today
- `llm/factory.py` builds two callers; `ResilientCaller(primary, fallback)` is hard-wired to two tiers with one breaker (primary only).
- `policy/resilience.py`: `Tier = primary | fallback | template`, `_TIER_RANK`, `worst_tier`, `degrade_verdict` (fallback/template never auto-approve).
- `graph/nodes.py:262` maps tier → model name from `large_model` / `small_model`; `_tier()` reads `caller.last_tier`.
- `GroqCaller` is built eagerly, so a missing `GROQ_API_KEY` would likely raise at startup.
- `langchain-anthropic` is not installed or in `pyproject.toml`.

## Design
**Tiers become four named slots:** `primary` (Sonnet), `secondary` (Groq 120b), `fallback` (Haiku), `template`.
Rank 0..3. Anything not `primary` is degraded: `degrade_verdict` turns `allow` into `needs_approval`
for `secondary`, `fallback` and `template` (fail closed; a degraded tier never auto-approves).

**`ResilientCaller` takes an ordered list of callers** instead of `(primary, fallback)`.
- Each tier gets its **own breaker** (Anthropic being down must not block Groq).
- Retry with jitter on transient errors for every tier except the last (as today the fallback gets one try).
- Bad output skips straight to the next tier (unchanged). All tiers fail → `ModelUnavailableError` → template tier (unchanged).
- `last_tier` reports the slot name that answered.

**Missing keys:** `build_caller` checks key presence in the environment (never prints it). A tier whose key is
missing is an `UnavailableCaller` that raises `ModelUnavailableError(kind="other")` at once: not transient, no retry,
no sleep, no breaker noise. The chain moves on; with no keys at all every call lands on the template tier:
template task → code + tests; unknown task → "cannot generate now" + Ticket. The tier label stays honest
(a Groq answer is `secondary` even if Anthropic is unset).

**Library:** `langchain-anthropic` (`ChatAnthropic.with_structured_output`), mirroring `GroqCaller`. One `AnthropicCaller(model)` class serves Sonnet and Haiku.

## Steps (test-first, none until approved)
1. **Dependency:** add `langchain-anthropic` to `pyproject.toml` (needs user OK; AGENTS.md rule). The user has not yet said yes to this one.
2. **Pure rules first (`policy/resilience.py`):** extend `Tier` and `_TIER_RANK` to four tiers; `degrade_verdict` covers `secondary`; update `test_resilience_rules.py` (rank order, degrade, `worst_tier`). Check `should_repair` and any other tier check in `policy/` for hard-coded `"fallback"`.
3. **Config:** `primary_model="claude-sonnet-5-5"`, `secondary_model="openai/gpt-oss-120b"`, `fallback_model="claude-haiku-5-5"`; keep `small_model` (Groq 20b) for the future handoff summary. Replace `large_model` (call sites: `nodes.py`, `scripts/trace_pipeline.py`, `test_config.py`). Optional env overrides added to `ENV_KEYS` **and** `.env.example`; fix the "not read yet" comment on `ANTHROPIC_API_KEY`.
4. **`AnthropicCaller`:** lazy import, `temperature=0`, `ValidationError`/`ValueError` → `ModelOutputError`, provider errors → `ModelUnavailableError(kind=classify_failure(exc))`. Client `max_retries=0` and a timeout so only our wrapper retries. Extend `classify_failure`: **529 "overloaded" → `server_unavailable`**; auth/400 → `other` (never retried).
5. **`UnavailableCaller`** + **`ResilientCaller(callers: list)`** with per-tier breakers; update `test_resilient_caller.py` and `test_resilient_graph.py` (fakes keep working via the list).
6. **Factory:** build the three slots from settings and key presence; chaos wraps each tier with a distinct seed; `scripts/chaos_run.py` passes 3 fakes (still 20 of 20 at 60% failures).
7. **Report label (`nodes.py:262`):** tier → configured model name for all three slots; "template" has no model. Update `test_report.py` if wording changes.
8. **Offline tests (no key, no network):** factory with all keys / only Groq / only Anthropic / none (none → every call raises `ModelUnavailableError`, graph returns template result or "cannot generate now" + Ticket); `classify_failure` table; breaker isolation (Sonnet down does not open Groq's).
9. **Live checks (user's keys, never printed):** L1 example + one denied request on Sonnet; then unset the Anthropic key and confirm the report names `secondary` / Groq and a risky request needs approval; unset both and confirm template behaviour. Log like `plans/2026-11-15-05-l1-live-groq-checks.md`.
10. **Docs:** README/flowchart tier labels; propose the AGENTS.md "Models" edit (not applied silently); TRACKER row evidence.

## Risks
- Anthropic structured output via tool-use may reject schemas Groq accepted; bad output already skips to the next tier, but check all agent schemas against Sonnet and Haiku.
- Cost: Claude is metered; a Run can make several calls plus up to 2 repairs. The run quota (5/day demo) bounds it. R4 stays out of scope.
- Groq-only dev runs will show `secondary` and require approval for every `allow` verdict (see open call).

## Decided: tier label
Label by **slot** (user agreed 2026-11-15). A Groq answer is `secondary` even when the Anthropic key is unset,
so a Groq-only setup needs approval for every `allow` verdict. Honest and fail closed.

## Still open
OK to add the `langchain-anthropic` dependency? (Blocks step 1; nothing is built until yes.)
