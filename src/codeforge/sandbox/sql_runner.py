"""R7: run an allowed SELECT against a fresh in-memory sample database. Fake data only."""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import BaseModel

from codeforge.config import Role
from codeforge.policy.sql_policy import MAX_ROWS, authorizer, bounded_query, evaluate_sql, schema_sql

# The progress handler fires every _TICK VM steps; a runaway query (e.g. recursive CTE) stops.
_TICK, _MAX_TICKS = 1_000, 2_000

_PRODUCTS = [("Notebook", "stationery", 3.5), ("Pen", "stationery", 1.2),
             ("Backpack", "bags", 24.0), ("Water bottle", "accessories", 9.5),
             ("Calculator", "electronics", 15.0), ("Headphones", "electronics", 39.0),
             ("Desk lamp", "home", 19.0), ("Sticky notes", "stationery", 2.0)]


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(schema_sql())
    conn.executemany("INSERT INTO products (name, category, price) VALUES (?, ?, ?)", _PRODUCTS)
    for table, year, n in (("sales", 2026, 60), ("archived_sales", 2025, 24)):
        rows = []
        for i in range(n):
            pid, qty = i % len(_PRODUCTS) + 1, i % 5 + 1
            rows.append((pid, qty, round(qty * _PRODUCTS[pid - 1][2], 2),
                         f"{year}-{i % 6 + 1:02d}-{i % 28 + 1:02d}"))
        conn.executemany(f"INSERT INTO {table} (product_id, quantity, amount, sold_on) "
                         "VALUES (?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO departments (name) VALUES (?)",
                     [("Engineering",), ("Teaching",), ("Operations",)])
    conn.executemany("INSERT INTO employees (name, department_id, salary) VALUES (?, ?, ?)",
                     [(f"Employee {i}", i % 3 + 1, 40_000 + 1_000 * i) for i in range(1, 10)])
    conn.executemany("INSERT INTO users (email, password_hash) VALUES (?, ?)",
                     [(f"user{i}@example.com", "fake-hash") for i in range(1, 4)])
    conn.commit()
    conn.execute("PRAGMA query_only = ON")


class SqlResult(BaseModel):
    columns: list[str] = []
    rows: list[tuple[Any, ...]] = []
    clamped: bool = False  # more than MAX_ROWS rows matched; only MAX_ROWS are returned
    error: str | None = None


def run_sql(sql: str, role: Role) -> SqlResult:
    """Run one query. Re-checks the policy and applies the same authorizer while running."""
    decision = evaluate_sql(sql, role)
    if decision.verdict != "allow":
        return SqlResult(error="denied: " + "; ".join(decision.reasons))
    conn = sqlite3.connect(":memory:")
    try:
        _seed(conn)
        conn.set_authorizer(authorizer(role, []))
        ticks = 0

        def budget() -> int:
            nonlocal ticks
            ticks += 1
            return int(ticks > _MAX_TICKS)  # non-zero aborts the query

        conn.set_progress_handler(budget, _TICK)
        cur = conn.execute(bounded_query(sql))
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description or []]
    except sqlite3.Error as e:
        return SqlResult(error=f"query stopped: {e}")
    finally:
        conn.close()
    return SqlResult(columns=columns, rows=rows[:MAX_ROWS], clamped=len(rows) > MAX_ROWS)


def format_result(result: SqlResult, max_bytes: int) -> str:
    """Plain-text table for the report, cut to max_bytes."""
    note = f" (clamped to {MAX_ROWS})" if result.clamped else ""
    lines = [f"{len(result.rows)} rows{note}", " | ".join(result.columns)]
    lines += [" | ".join(str(v) for v in row) for row in result.rows]
    return "\n".join(lines).encode()[:max_bytes].decode(errors="ignore")
