"""R7: the SQL policy and runner (plans/queries.md section 10). Pure rules, no model."""

import pytest

from codeforge.policy.sql_policy import MAX_ROWS, evaluate_sql
from codeforge.sandbox.sql_runner import run_sql

TOP_FIVE = ("SELECT p.name, SUM(s.amount) AS total FROM sales s JOIN products p "
            "ON p.id = s.product_id GROUP BY p.name ORDER BY total DESC LIMIT 5")
BY_DEPT = ("SELECT d.name, COUNT(*) FROM employees e JOIN departments d "
           "ON d.id = e.department_id GROUP BY d.name")
CTE = ("WITH m AS (SELECT strftime('%Y-%m', sold_on) AS month, SUM(amount) AS total "
       "FROM sales GROUP BY month) SELECT * FROM m ORDER BY month")
UNION = "SELECT id, amount FROM sales UNION ALL SELECT id, amount FROM archived_sales"


@pytest.mark.parametrize("sql", [TOP_FIVE, CTE, UNION, TOP_FIVE + ";"])
def test_read_only_queries_are_allowed_for_instructors(sql):
    assert evaluate_sql(sql, "instructor").verdict == "allow"


@pytest.mark.parametrize("sql", [TOP_FIVE, "SELECT 1"])
def test_students_may_not_use_the_sql_agent(sql):
    decision = evaluate_sql(sql, "student")
    assert decision.verdict == "deny" and "instructors only" in decision.reasons[0]


def test_employees_allowed_for_instructor_not_student():
    assert evaluate_sql(BY_DEPT, "instructor").verdict == "allow"
    decision = evaluate_sql(BY_DEPT, "student")
    assert decision.verdict == "deny"
    assert decision.reasons


@pytest.mark.parametrize("sql, reason", [
    ("SELECT * FROM users", "users"),
    ("DROP TABLE sales", "SELECT"),
    ("DELETE FROM sales", "SELECT"),
    ("SELECT * FROM sales; DELETE FROM sales;", "one statement"),
    ("ATTACH DATABASE 'other.db' AS other", "SELECT"),
    ("SELECT * FROM sqlite_master", "sqlite_master"),
    ("SELECT name FROM sqlite_schema", "sqlite_master"),  # an alias of sqlite_master
    ("PRAGMA table_info(users)", "SELECT"),
    ("SELECT load_extension('x')", "load_extension"),
    # Table-valued PRAGMAs only hit the PRAGMA authorizer at run time; the policy must deny them.
    ("SELECT seq, name, file FROM pragma_database_list", "pragma_database_list"),
    ("SELECT * FROM pragma_table_info('users')", "pragma_table_info"),
    ("SELECT name FROM pragma_table_list", "pragma_table_list"),
    ("SELECT * FROM sales WHERE id IN (SELECT id FROM users)", "users"),
    ("SELEKT * FROM sales", "invalid"),
    ("", "empty"),
])
def test_denied(sql, reason):
    decision = evaluate_sql(sql, "instructor")
    assert decision.verdict == "deny"
    assert any(reason in r for r in decision.reasons), decision.reasons


def test_trailing_comment_cannot_escape_the_row_limit():
    result = run_sql("SELECT * FROM sales -- )", "instructor")
    assert result.error is None and len(result.rows) <= MAX_ROWS


def test_large_limit_is_clamped():
    result = run_sql("SELECT a.id FROM sales a, sales b LIMIT 10000000", "instructor")
    assert result.error is None
    assert len(result.rows) == MAX_ROWS and result.clamped


def test_top_five_runs_and_returns_rows():
    result = run_sql(TOP_FIVE, "instructor")
    assert result.error is None
    assert result.columns == ["name", "total"] and len(result.rows) == 5
    assert not result.clamped


def test_runaway_recursive_cte_is_stopped():
    sql = ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
           "SELECT COUNT(*) FROM r")
    result = run_sql(sql, "instructor")
    assert result.error and "interrupted" in result.error


def test_runner_refuses_what_the_policy_denies():
    # Defence in depth: the runner applies the same authorizer, never trusting the caller.
    result = run_sql("SELECT * FROM users", "instructor")
    assert result.error and result.rows == []


def test_sql_prompt_shows_every_table_so_code_not_the_model_denies():
    # A model that only sees allowed tables answers "no such table" instead of trying, so
    # the denial is never shown. The authorizer, not the prompt, is the access control.
    from codeforge.agents.sqlgen import _system
    from codeforge.policy.sql_policy import TABLES
    prompt = _system()
    assert all(f"CREATE TABLE {t} " in prompt for t in TABLES)
