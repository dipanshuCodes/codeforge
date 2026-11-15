from solution import total


def test_list():
    assert total([1, 2, 3]) == 6


def test_tuple():
    assert total((4, 5, 6)) == 15


def test_empty_list_and_tuple():
    assert total([]) == 0
    assert total(()) == 0


def test_floats():
    assert total([0.5, 0.25]) == 0.75
