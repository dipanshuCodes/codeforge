from codeforge.agents.schemas import CodeOutput, Requirements
from codeforge.llm.caller import StructuredCaller


def _system(req: Requirements) -> str:
    return (
        f"Write one self-contained Python 3.11 module that defines a top-level function "
        f"`{req.function_name}`.\n"
        "Use the standard library only. No I/O, network, file or environment access, and no "
        "code that runs at import time apart from definitions.\n"
        "Do not use dunder names or dunder attributes, including __all__, __dict__, "
        "__globals__ or __builtins__. Do not add module metadata or unnecessary "
        "module-level variables. Only define the requested function.\n"
        "Return only the module source."
    )


def generate_code(caller: StructuredCaller, req: Requirements) -> CodeOutput:
    return caller.call(CodeOutput, _system(req), f"Specification (JSON):\n{req.model_dump_json(indent=2)}")
