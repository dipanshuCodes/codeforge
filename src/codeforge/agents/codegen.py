from codeforge.agents.schemas import CodeOutput, Requirements
from codeforge.llm.caller import StructuredCaller


def _system(req: Requirements) -> str:
    return (
        f"Write one self-contained Python 3.11 module that defines a top-level function "
        f"`{req.function_name}`.\n"
        "Use the standard library only. No I/O, network, file or environment access, and no "
        "code that runs at import time apart from definitions. Return only the module source."
    )


def generate_code(caller: StructuredCaller, req: Requirements) -> CodeOutput:
    return caller.call(CodeOutput, _system(req), f"Specification (JSON):\n{req.model_dump_json(indent=2)}")
