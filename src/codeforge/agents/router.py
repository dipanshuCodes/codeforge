from codeforge.agents.schemas import RouterOutput
from codeforge.llm.caller import StructuredCaller

SYSTEM = (
    "You classify a student's request on a coding course platform.\n"
    "Answer python_function if they want a single Python function (or a small set of helpers "
    "around one function) written.\n"
    "Answer sql_query if they want a SQL query.\n"
    "Answer other for anything else: other languages, multi-file projects, services, questions "
    "that are not a request for code."
)


def classify(caller: StructuredCaller, request: str) -> RouterOutput:
    return caller.call(RouterOutput, SYSTEM, f"Request:\n{request}")
