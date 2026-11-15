import pytest

from solution import factorial


def test_values():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120


def test_negative_raises():
    with pytest.raises(ValueError):
        factorial(-1)
