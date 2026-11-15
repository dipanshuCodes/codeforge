from solution import flatten


def test_basic():
    assert flatten([[1, 2], [3], [4, 5]]) == [1, 2, 3, 4, 5]


def test_empty_inner_lists():
    assert flatten([[], [1], []]) == [1]


def test_only_one_level():
    assert flatten([[1, [2]], [3]]) == [1, [2], 3]
