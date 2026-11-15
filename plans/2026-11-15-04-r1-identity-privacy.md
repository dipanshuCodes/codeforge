# R1 Identity and privacy

Issue: dipanshuCodes/codeforge#4 · Owner: Siyahul · Branch: `feat/r1-identity-privacy`

## What changes

- **Masking** (`privacy/masking.py`, pure): `[SECRET]` → `[EMAIL]` → `[CARD]` (13–19 digits,
  spaces/dashes allowed, kept unless Luhn passes) → `[AADHAAR]` (12 digits starting 2–9, no
  checksum) → `[PHONE]` (10 digits starting 6–9, optional `+91`/`0`). Idempotent. An Aadhaar
  match never starts right after `+`, so `+91…` stays a phone.
- **Run quota** (`policy/quota.py`, pure): `quota_allows(used, limit)`, `counts_toward_quota`,
  `quota_window_start`. The store counts the config User's Runs since the window start,
  excluding `cannot_generate` (Transient failure) and `quota_exceeded`. Runs in progress count.
- **Ingress** masks first, then checks the quota before saving the new Run. Over the limit, the
  Run is stored with outcome `quota_exceeded` and the graph goes straight to `report`, so no
  model is called. New report headline: `QUOTA REACHED: N Requests per day`.
- **Config:** `CODEFORGE_RUN_QUOTA` (default 5; must be a positive whole number, else
  `ConfigError`). In `ENV_KEYS` and `.env.example`.
- Identity already comes only from config; tests prove a message claiming "instructor" or
  another user id changes neither the role, the owner of the Run, nor the quota.

## Assumptions

- UNRESOLVED: the daily window is the **UTC** day. IST midnight is 18:30 UTC; switch to IST if
  the team prefers, it is one line in `quota_window_start`'s caller.
- `quota_exceeded` is a new Outcome. It is a refusal, not a Final outcome, and does not count
  toward the quota.
- Golden cases (identity, isolation, quota) are written as graph tests now and move into
  `evals/golden_set.json` with R6, which does not exist yet.
- The README "developers only" warning stays until R2 is done too.
