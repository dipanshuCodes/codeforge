
"""SQLite run store. Student queries are scoped to the config User.
Instructor approval queries can view pending Runs across students.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from codeforge.config import Settings
from codeforge.privacy.masking import mask
from codeforge.reporting.outcome import FINAL_OUTCOMES, Outcome

_FIELDS = (
    "run_id", "conversation_id", "created_at", "request", "kind", "outcome", "verdict",
    "reasons", "approved", "code", "tests", "exit_code", "timed_out", "output",
    "serving_tier", "report", "request_key", "duplicate_of",
)

_INT_FIELDS = ("approved", "exit_code", "timed_out")

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    {", ".join(f"{f} {'INTEGER' if f in _INT_FIELDS else 'TEXT'}" for f in _FIELDS[1:])}
)
"""

_EXECUTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    execution_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    exit_code INTEGER,
    timed_out INTEGER NOT NULL,
    output TEXT NOT NULL,
    PRIMARY KEY (execution_key, user_id)
)
"""

_TICKETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    serving_tier TEXT,
    request TEXT NOT NULL
)
"""
# Added by R3; older databases get them through ALTER TABLE in RunStore.__init__.
_TICKET_EXTRA = {"priority": "TEXT", "sla_hours": "INTEGER", "handoff_note": "TEXT"}


_FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL
)
"""


class FeedbackRecord(BaseModel):
    """A User's thumbs-down on one of their own Runs. `reason` is always masked."""

    feedback_id: str
    run_id: str
    created_at: str
    reason: str


class TicketRecord(BaseModel):
    """A Ticket. R5's outage Ticket has no priority; R3 Escalations set priority, SLA and note."""

    ticket_id: str
    run_id: str
    created_at: str
    reason: str
    serving_tier: str | None = None
    request: str  # always the masked Request
    priority: str | None = None
    sla_hours: int | None = None
    handoff_note: str | None = None  # rendered from masked fields only


class PendingApproval(BaseModel):
    """A masked student Request awaiting instructor approval."""

    run_id: str
    student_id: str
    conversation_id: str
    created_at: str
    request: str
    reasons: list[str] = Field(default_factory=list)
    code: str | None = None
    tests: str | None = None
    serving_tier: str | None = None

class RunRecord(BaseModel):
    """One Run. The store adds its owner from configuration."""

    run_id: str
    conversation_id: str
    created_at: str
    request: str
    kind: str | None = None
    outcome: Outcome | None = None
    verdict: str | None = None
    reasons: list[str] = Field(default_factory=list)
    approved: bool | None = None
    code: str | None = None
    tests: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    output: str | None = None
    serving_tier: str | None = None
    report: str | None = None
    request_key: str | None = None
    duplicate_of: str | None = None


class RunStore:
    def __init__(self, settings: Settings) -> None:
        self._user_id = settings.user_id
        self._role = settings.role
        self._db_path = settings.db_path

        with closing(self._connect()) as conn, conn:
            conn.execute(_SCHEMA)
            conn.execute(_TICKETS_SCHEMA)
            conn.execute(_EXECUTIONS_SCHEMA)
            conn.execute(_FEEDBACK_SCHEMA)
            # Databases made before a column existed get it added (no data is changed).
            have = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
            for f in _FIELDS:
                if f not in have:
                    kind = "INTEGER" if f in _INT_FIELDS else "TEXT"
                    conn.execute(f"ALTER TABLE runs ADD COLUMN {f} {kind}")
            have = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
            for f, kind in _TICKET_EXTRA.items():
                if f not in have:
                    conn.execute(f"ALTER TABLE tickets ADD COLUMN {f} {kind}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, record: RunRecord) -> None:
        """Save a Run owned by the configured user."""

        values = record.model_dump()
        values["reasons"] = json.dumps(values["reasons"])

        cols = ("user_id",) + _FIELDS
        params = [self._user_id] + [
            values[field] for field in _FIELDS
        ]

        updates = ", ".join(
            f"{field} = excluded.{field}"
            for field in _FIELDS[1:]
        )

        sql = (
            f"INSERT INTO runs ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(run_id) DO UPDATE SET {updates} "
            "WHERE runs.user_id = excluded.user_id"
        )

        with closing(self._connect()) as conn, conn:
            conn.execute(sql, params)

    def get(self, run_id: str) -> RunRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ? AND user_id = ?",
                (run_id, self._user_id),
            ).fetchone()

        return _to_record(row) if row else None

    def count_since(
        self,
        since_iso: str,
        not_counted: frozenset[str],
    ) -> int:
        marks = ", ".join("?" for _ in not_counted)

        excluded = (
            f"AND (outcome IS NULL OR outcome NOT IN ({marks}))"
            if not_counted
            else ""
        )

        with closing(self._connect()) as conn:
            (count,) = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM runs
                WHERE user_id = ?
                  AND created_at >= ?
                  {excluded}
                """,
                (self._user_id, since_iso, *sorted(not_counted)),
            ).fetchone()

        return count

    def add_ticket(self, run_id: str, reason: str, serving_tier: str | None, request: str, *,
                   priority: str | None = None, sla_hours: int | None = None,
                   handoff_note: str | None = None) -> str:
        """Open a Ticket for the config User. `request` and `handoff_note` must already be masked."""
        ticket_id = uuid.uuid4().hex

        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO tickets (ticket_id, user_id, run_id, created_at, reason, serving_tier,"
                " request, priority, sla_hours, handoff_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticket_id, self._user_id, run_id, datetime.now(timezone.utc).isoformat(), reason,
                 serving_tier, request, priority, sla_hours, handoff_note),
            )

        return ticket_id

    def list_tickets(self) -> list[TicketRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT ticket_id, run_id, created_at, reason, serving_tier, request, priority,"
                " sla_hours, handoff_note FROM tickets"
                " WHERE user_id = ? ORDER BY created_at", (self._user_id,)
            ).fetchall()

        return [TicketRecord(**dict(row)) for row in rows]

    def add_feedback(self, run_id: str, reason: str) -> str | None:
        """Store Feedback on the config User's own Run. None if the Run is missing or not
        theirs (indistinguishable). The reason is user text, so it is masked here."""
        if self.get(run_id) is None:
            return None
        feedback_id = uuid.uuid4().hex
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO feedback (feedback_id, user_id, run_id, created_at, reason)"
                " VALUES (?, ?, ?, ?, ?)",
                (feedback_id, self._user_id, run_id, datetime.now(timezone.utc).isoformat(),
                 mask(reason)),
            )
        return feedback_id

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT feedback_id, run_id, created_at, reason FROM feedback"
                " WHERE feedback_id = ? AND user_id = ?", (feedback_id, self._user_id),
            ).fetchone()
        return FeedbackRecord(**dict(row)) if row else None

    def find_final_run(self, request_key: str) -> RunRecord | None:
        """The config User's newest original Run with this Request key and a Final outcome."""
        marks = ", ".join("?" for _ in FINAL_OUTCOMES)

        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM runs
                WHERE user_id = ?
                  AND request_key = ?
                  AND duplicate_of IS NULL
                  AND outcome IN ({marks})
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    self._user_id,
                    request_key,
                    *sorted(FINAL_OUTCOMES),
                ),
            ).fetchone()

        return _to_record(row) if row else None

    def get_execution(
        self,
        execution_key: str,
    ) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT exit_code, timed_out, output
                FROM executions
                WHERE execution_key = ? AND user_id = ?
                """,
                (execution_key, self._user_id),
            ).fetchone()

        if row is None:
            return None

        return {
            "exit_code": row["exit_code"],
            "timed_out": bool(row["timed_out"]),
            "output": row["output"],
        }

    def save_execution(
        self,
        execution_key: str,
        result: dict,
    ) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO executions VALUES (?, ?, ?, ?, ?)",
                (
                    execution_key,
                    self._user_id,
                    result["exit_code"],
                    int(result["timed_out"]),
                    result["output"],
                ),
            )

    def list_pending_approvals(self) -> list[PendingApproval]:
        """List pending approval Requests across students. Instructor only."""

        if self._role != "instructor":
            raise PermissionError(
                "Only instructors can view pending approvals."
            )

        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT run_id, user_id, conversation_id,
                       created_at, request, reasons, code,
                       tests, serving_tier
                FROM runs
                WHERE verdict = 'needs_approval'
                  AND approved IS NULL
                  AND outcome IS NULL
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [
            PendingApproval(
                run_id=row["run_id"],
                student_id=row["user_id"],
                conversation_id=row["conversation_id"],
                created_at=row["created_at"],
                request=row["request"],
                reasons=json.loads(row["reasons"] or "[]"),
                code=row["code"],
                tests=row["tests"],
                serving_tier=row["serving_tier"],
            )
            for row in rows
        ]

    def list_mine(self) -> list[RunRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM runs
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (self._user_id,),
            ).fetchall()

        return [_to_record(row) for row in rows]


def _to_record(row: sqlite3.Row) -> RunRecord:
    data = {
        field: row[field]
        for field in _FIELDS
    }

    data["reasons"] = json.loads(data["reasons"] or "[]")
    data["timed_out"] = bool(data["timed_out"])

    if data["approved"] is not None:
        data["approved"] = bool(data["approved"])

    return RunRecord(**data)
