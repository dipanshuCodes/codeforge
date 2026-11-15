"""Template tier (R5): hand-written solutions for a few known tasks, used in a total outage.

Matching is strict: every required word group present, no blocking word, and **exactly one**
template matching. Anything else returns None and the graph says "cannot generate now".
Never invents code for an unknown task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from codeforge.agents.schemas import Param, Requirements

# Words that make any template unsafe to use: the Request wants more than the template does.
_GLOBAL_BLOCKING = frozenset({
    "delete", "remove", "file", "files", "folder", "directory", "network", "http", "url",
    "download", "shell", "subprocess", "sql", "database", "then", "and",
})


@dataclass(frozen=True)
class Template:
    name: str
    required: tuple[tuple[str, ...], ...]  # every group needs at least one of its words
    blocking: frozenset[str]
    requirements: Requirements
    code: str
    tests: str


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", text.lower()))


def _tests(fn: str, body: str) -> str:
    return f"from solution import {fn}\n\n{body}"


TEMPLATES: tuple[Template, ...] = (
    Template(
        name="sum_list",
        required=(("sum", "total"), ("list", "array")),
        blocking=frozenset({"digit", "digits", "product", "average", "mean", "string", "nested",
                            "tuple", "sort", "sorts", "sorted", "reverse", "even", "odd"}),
        requirements=Requirements(function_name="sum_list", description="Sum of a list of numbers.",
                                  params=[Param(name="values", type="list[float]")],
                                  returns="float", edge_cases=["empty list returns 0"]),
        code="def sum_list(values):\n    return sum(values)\n",
        tests=_tests("sum_list", "def test_sum():\n    assert sum_list([1, 2, 3]) == 6\n\n"
                                 "def test_empty():\n    assert sum_list([]) == 0\n"),
    ),
    Template(
        name="is_palindrome",
        required=(("palindrome", "palindromic"),),
        blocking=frozenset({"substring", "longest", "number", "integer", "linked", "permutation",
                            "count", "partition"}),
        requirements=Requirements(function_name="is_palindrome", description="Palindrome check.",
                                  params=[Param(name="s", type="str")], returns="bool",
                                  edge_cases=["empty string is a palindrome"]),
        code="def is_palindrome(s):\n    return s == s[::-1]\n",
        tests=_tests("is_palindrome", "def test_yes():\n    assert is_palindrome('aba')\n\n"
                                      "def test_no():\n    assert not is_palindrome('ab')\n\n"
                                      "def test_empty():\n    assert is_palindrome('')\n"),
    ),
    Template(
        name="reverse_string",
        required=(("reverse", "reversed"), ("string", "text")),
        blocking=frozenset({"word", "words", "sentence", "linked", "list", "number", "integer",
                            "array", "palindrome", "factorial"}),
        requirements=Requirements(function_name="reverse_string", description="Reverse a string.",
                                  params=[Param(name="s", type="str")], returns="str",
                                  edge_cases=["empty string"]),
        code="def reverse_string(s):\n    return s[::-1]\n",
        tests=_tests("reverse_string", "def test_basic():\n    assert reverse_string('abc') == 'cba'\n\n"
                                       "def test_empty():\n    assert reverse_string('') == ''\n"),
    ),
    Template(
        name="factorial",
        required=(("factorial",),),
        blocking=frozenset({"trailing", "digits", "digit", "sum", "double", "subfactorial",
                            "zeros", "reverse", "palindrome"}),
        requirements=Requirements(function_name="factorial", description="Factorial of n >= 0.",
                                  params=[Param(name="n", type="int")], returns="int",
                                  edge_cases=["0! is 1", "negative n raises ValueError"]),
        code=("def factorial(n):\n    if n < 0:\n        raise ValueError('n must be >= 0')\n"
              "    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result\n"),
        tests=_tests("factorial", "import pytest\n\ndef test_zero():\n    assert factorial(0) == 1\n\n"
                                  "def test_five():\n    assert factorial(5) == 120\n\n"
                                  "def test_negative():\n    with pytest.raises(ValueError):\n"
                                  "        factorial(-1)\n"),
    ),
)


def _matches(t: Template, words: frozenset[str]) -> bool:
    if words & _GLOBAL_BLOCKING or words & t.blocking:
        return False
    return all(words & set(group) for group in t.required)


def pick_template(request: str) -> Template | None:
    """The one matching template, or None (no match, or ambiguous)."""
    words = _tokens(request)
    found = [t for t in TEMPLATES if _matches(t, words)]
    return found[0] if len(found) == 1 else None
