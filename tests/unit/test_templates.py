import ast

import pytest

from codeforge.policy.templates import TEMPLATES, pick_template


@pytest.mark.parametrize("text,name", [
    ("Write a function that returns the sum of a list of numbers", "sum_list"),
    ("write a python function to check if a string is a palindrome", "is_palindrome"),
    ("Please reverse a string for me", "reverse_string"),
    ("compute the factorial of n", "factorial"),
])
def test_exactly_one_match_returns_the_template(text, name):
    assert pick_template(text).name == name


@pytest.mark.parametrize("text", [
    "sum of the digits of a number",          # look-alike: not a list sum
    "sum a list and then delete my files",     # blocking word
    "reverse a linked list",                   # look-alike
    "reverse the words in a sentence",
    "find the longest palindromic substring",
    "count trailing zeros of a factorial",
    "write a function that sorts a list",      # unknown task
    "",
])
def test_lookalikes_and_unknown_tasks_match_nothing(text):
    assert pick_template(text) is None


def test_two_matches_is_ambiguous_so_none():
    assert pick_template("reverse a string and compute the factorial") is None


def test_templates_are_valid_python_with_matching_function_names():
    for t in TEMPLATES:
        tree = ast.parse(t.code)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert t.requirements.function_name in names
        ast.parse(t.tests)
        assert f"from solution import {t.requirements.function_name}" in t.tests
