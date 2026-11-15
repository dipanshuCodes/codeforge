import pytest

from solution import second_largest


def test_basic():
    assert second_largest([3, 1, 4, 1, 5]) == 4


def test_duplicates_of_max():
    assert second_largest([5, 5, 2]) == 2


def test_negatives():
    assert second_largest([-1, -3, -2]) == -2


def test_too_few_distinct_raises():
    with pytest.raises(ValueError):
        second_largest([7, 7])
