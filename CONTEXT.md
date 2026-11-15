# CodeForge

A multi-agent system on a course platform that turns a student's plain-English request into
code and tests, runs them, and honestly reports what happened.

## Language

### Work items

**Masking**:
Replacing secrets and personal data in user text with typed placeholders (`[SECRET]`,
`[EMAIL]`, `[CARD]`, `[AADHAAR]`, `[PHONE]`) at ingress, before anything else sees it.
_Avoid_: redaction, sanitising

**Request**:
The masked text a user submits in one turn.
_Avoid_: prompt, query, message (when meaning the unit of work)

**Conversation**:
The sequence of Requests one user makes in a single console or UI session. Escalation signals
(unhappy turns, policy denials) accumulate across a Conversation.
_Avoid_: session, chat, thread

**Run**:
One end-to-end processing of a Request, owned by the user who submitted it. It records the
outcome: the verdict, code, tests and report. Runs are what ownership protects. A denied
Request is still a Run.

**Run quota**:
The number of Requests a User may submit. Every submitted Request counts, Duplicate Requests
included, except those ending in a Transient failure.
_Avoid_: rate limit, credits
_Avoid_: job, task, session

**Execution**:
One sandboxed pytest invocation inside a Run. A Run has one to three Executions: the original
attempt plus up to two Repair attempts.
_Avoid_: run (when meaning the sandbox step), test run

**Repair attempt**:
A regeneration within the same Run after an Execution's tests fail, using the failing pytest
output as feedback. Two failed Repair attempts escalate the Run to a human.
_Avoid_: retry (reserved for transient provider errors)

**Duplicate Request**:
A Request from the same user with the same masked text as an earlier one. If the earlier Run
reached a Final outcome, it is returned instead of starting a new Run. If that Run is still
awaiting approval, it is resumed rather than duplicated.
_Avoid_: retry, resubmission

**Request key**:
The hash of user and masked Request text. It identifies Duplicate Requests.

**Execution key**:
The hash of user, code and tests. An Execution with a key already seen returns the stored
result instead of running again.
_Avoid_: idempotency key (ambiguous: there are two keys)

**Final outcome**:
The settled result of a Run: tests passed, tests failed, timed out, denied, unsupported, or
rejected by the approver, or escalated (a P1 Ticket handed the Run to a human with nothing
generated). A Transient failure is not a Final outcome.

**Transient failure**:
A Run that ended because CodeForge could not serve it at that moment, for example "cannot
generate now" during a provider outage. Resubmitting it starts a new Run.

### Quality

**Feedback**:
A User's thumbs-down on a Run, with an optional reason. Raw material for new Golden cases.
_Avoid_: rating, review

**Golden case**:
A fixed input with a human-decided expected outcome, part of the gate that decides whether a
build can ship. Hard cases must always pass; soft cases must pass at 85% or more.
_Avoid_: test case (ambiguous with generated tests), fixture

**Reference test**:
A hidden, human-written test that judges whether generated code is correct. Never written by a
model.
_Avoid_: generated test, expected test

### Serving

**Serving tier**:
What produced a Run's code and tests: the primary model, the fallback model, or the Template
tier. Every report names it.

**Template tier**:
The last-resort Serving tier: a fixed library of hand-written code and tests for a few common
tasks, used when no model is available. It never invents code for tasks outside the library.
_Avoid_: cache, offline mode

**Chaos switch**:
A setting that makes a share of model calls fail on purpose (rate limits, provider errors,
timeouts, bad output) to show that CodeForge still answers.
_Avoid_: fault mode, test mode

### Escalation

**Escalation**:
Handing a Conversation to a human because a rule in code says so (a request for a person,
anger, repeated unhappiness, repeated denials, or failed Repair attempts).
_Avoid_: handoff (that is the note), support request

**Ticket**:
The record an Escalation creates, with a priority (P1–P3), an SLA and a Handoff note.
Contains only masked text.

**Handoff note**:
The part of a Ticket that tells the human what happened: a brief summary, the Request, the
attempts, and the last failing test.

### People

**User**:
The identity from config that submits Requests and owns Runs, with a role of `student` or
`instructor`. Never inferred from message text.
_Avoid_: account, customer

**Approver**:
The human at the console or UI who approves or rejects a paused Run. An action, not a role:
being an Approver requires no particular User role.
_Avoid_: reviewer, admin, instructor (when meaning the Approver)

### Classification

**Request kind**:
The Router's classification of a Request: `python_function`, `sql_query` or `other`.

**Unsupported Request**:
A Request whose kind CodeForge does not serve. It gets an honest "not supported" report and no
code. For now this covers `other` and `sql_query`.
