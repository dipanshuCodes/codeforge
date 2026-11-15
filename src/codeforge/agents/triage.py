from codeforge.agents.schemas import TriageOutput
from codeforge.llm.caller import StructuredCaller

SYSTEM = (
    "You read one message from a student on a coding course platform and report signals only.\n"
    "language: the ISO 639-1 code of the message's language.\n"
    "sentiment: calm, mildly_unhappy (frustrated, complaining) or angry (shouting, hostile).\n"
    "urgency: high if they say it is urgent or blocking them now, else low.\n"
    "wants_human: true only if they ask for a person (a human, a teacher, support, a real "
    "person). Do not decide anything else."
)


def triage(caller: StructuredCaller, request: str) -> TriageOutput:
    return caller.call(TriageOutput, SYSTEM, f"Message:\n{request}")
