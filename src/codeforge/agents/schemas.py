"""Structured outputs of the L1 agents. Agents return these; they never decide."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RouterOutput(BaseModel):
    kind: Literal["python_function", "sql_query", "other"]


class Param(BaseModel):
    name: str
    type: str


class Requirements(BaseModel):
    function_name: str = Field(description="A valid Python identifier")
    description: str
    params: list[Param]
    returns: str
    edge_cases: list[str]


class CodeOutput(BaseModel):
    code: str = Field(description="The complete Python module source")


class TestsOutput(BaseModel):
    __test__ = False  # not a pytest test class, despite the name

    tests: str = Field(description="The complete pytest module source")


class RepairOutput(BaseModel):
    """Repair attempt 2: the agent may return changed tests as well as changed code."""

    code: str = Field(description="The complete corrected Python module source")
    tests: str = Field(description="The complete pytest module source")
