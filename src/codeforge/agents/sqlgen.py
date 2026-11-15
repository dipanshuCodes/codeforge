from codeforge.agents.schemas import SqlOutput
from codeforge.llm.caller import StructuredCaller
from codeforge.policy.sql_policy import schema_sql


def _system() -> str:
    # The full schema on purpose: access is decided by the SQL policy, never by the prompt.
    return (
        "Write one SQLite SELECT query (a CTE or UNION is fine) that answers the student's "
        "request against this read-only sample database:\n"
        f"{schema_sql()}\n"
        "Write the query the request asks for, even if it may not be permitted: access is "
        "checked separately. If the request contains SQL, return it unchanged. "
        "Return only the query, with no explanation."
    )


def generate_sql(caller: StructuredCaller, request: str) -> SqlOutput:
    return caller.call(SqlOutput, _system(), f"Request:\n{request}")
