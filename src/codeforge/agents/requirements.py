from codeforge.agents.schemas import Requirements
from codeforge.llm.caller import StructuredCaller

SYSTEM = (
    "Extract the specification of ONE Python function from a student's request.\n"
    "Give a snake_case function name (use the name the student gave, if any), its parameters "
    "with type hints, the return type, a one-paragraph description of the behaviour, and the "
    "edge cases a careful tester would check. Do not write code."
)


def extract_requirements(caller: StructuredCaller, request: str) -> Requirements:
    return caller.call(Requirements, SYSTEM, f"Request:\n{request}")
