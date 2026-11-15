"""R7: SQL policy. The model writes SQL; SQLite's own compiler, behind an authorizer, decides.

`evaluate_sql` compiles (EXPLAIN, never runs) the query against an empty in-memory copy of
the sample schema. The authorizer sees every table, column and function the statement
touches, including inside CTEs, subqueries and UNIONs, so no text matching is needed.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from codeforge.config import Role
from codeforge.policy.code_policy import PolicyDecision

MAX_ROWS = 100  # every query is wrapped in an outer LIMIT; a larger LIMIT is clamped

# Sample database schema (R7). `users` is protected: no role may read it.
TABLES: dict[str, str] = {
    "products": "id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL",
    "sales": "id INTEGER PRIMARY KEY, product_id INTEGER, quantity INTEGER, amount REAL, sold_on TEXT",
    "archived_sales": "id INTEGER PRIMARY KEY, product_id INTEGER, quantity INTEGER, amount REAL, sold_on TEXT",
    "departments": "id INTEGER PRIMARY KEY, name TEXT",
    "employees": "id INTEGER PRIMARY KEY, name TEXT, department_id INTEGER, salary REAL",
    "users": "id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT",
}
_SALES = frozenset({"products", "sales", "archived_sales"})
# The brief: the SQL agent is for the instructor role only (from config).
READABLE: dict[str, frozenset[str]] = {
    "student": frozenset(),
    "instructor": _SALES | {"employees", "departments"},
}
FUNCTIONS = frozenset({
    "count", "sum", "avg", "min", "max", "total", "group_concat", "round", "abs", "lower",
    "upper", "length", "substr", "substring", "trim", "ltrim", "rtrim", "replace", "instr",
    "coalesce", "ifnull", "nullif", "iif", "printf", "format", "strftime", "date", "time",
    "datetime", "julianday", "row_number", "rank", "dense_rank", "lag", "lead",
})
_ALWAYS_OK = (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE)


def sql_allowed(role: Role) -> bool:
    return bool(READABLE[role])


def schema_sql(tables: frozenset[str] | set[str] | None = None) -> str:
    names = TABLES if tables is None else [t for t in TABLES if t in tables]
    return "\n".join(f"CREATE TABLE {t} ({TABLES[t]});" for t in names)


def _readable(name: str | None, readable: frozenset[str]) -> bool:
    """A CTE's own name also shows up as a READ. Any name that is not a real table of the
    sample schema (nor sqlite_*) can only be a CTE or alias, which reads real tables in turn."""
    if not name:
        return False
    if name.lower().startswith(("sqlite_", "pragma_")):
        return False  # schema tables and table-valued PRAGMAs (which only hit PRAGMA at run time)
    if name in TABLES:
        return name in readable
    return True


def authorizer(role: Role, reasons: list[str]) -> Callable[..., int]:
    """SQLite authorizer: SELECT/READ on the role's tables and allow-listed functions only.
    Everything else (writes, DDL, ATTACH, PRAGMA, sqlite_master) is denied."""
    readable = READABLE[role]

    def check(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trig: str | None) -> int:
        if action in _ALWAYS_OK:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and _readable(arg1, readable):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            reasons.append(f"table `{arg1}` is not readable for role {role}")
        elif action == sqlite3.SQLITE_FUNCTION:
            reasons.append(f"function `{arg2}` is not allowed")
        else:
            reasons.append("only a read-only SELECT statement is allowed")
        return sqlite3.SQLITE_DENY

    return check


def _body(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def bounded_query(sql: str) -> str:
    """The query as it runs: wrapped so at most MAX_ROWS + 1 rows come back (+1 shows a clamp).
    Newlines keep a trailing `--` comment from swallowing the closing parenthesis."""
    return f"SELECT * FROM (\n{_body(sql)}\n) LIMIT {MAX_ROWS + 1}"


def _deny(*reasons: str) -> PolicyDecision:
    return PolicyDecision(verdict="deny", reasons=list(dict.fromkeys(reasons)))


def evaluate_sql(sql: str, role: Role) -> PolicyDecision:
    """allow or deny, with reasons. Compiles only; nothing is executed. Fails closed."""
    if not READABLE[role]:
        return _deny(f"the SQL agent is for instructors only (role from config: {role})")
    body = _body(sql)
    if not body:
        return _deny("empty query")
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(schema_sql())
        reasons: list[str] = []
        conn.set_authorizer(authorizer(role, reasons))
        # The bare query must compile alone, so stray parentheses can't escape the wrapper.
        for statement in (body, bounded_query(body)):
            try:
                conn.execute("EXPLAIN " + statement)
            except sqlite3.ProgrammingError:
                return _deny("only one statement is allowed")
            except sqlite3.DatabaseError as e:
                return _deny(*reasons) if reasons else _deny(f"invalid SQL: {e}")
    finally:
        conn.close()
    return PolicyDecision(verdict="allow",
                          reasons=[f"read-only SELECT; at most {MAX_ROWS} rows returned"])


validate_sql = evaluate_sql  # the brief's name for this check
