from solution import fibonacci


def test_base_cases():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1


def test_sequence():
    assert [fibonacci(n) for n in range(2, 11)] == [1, 2, 3, 5, 8, 13, 21, 34, 55]


def test_larger():
    assert fibonacci(30) == 832040
