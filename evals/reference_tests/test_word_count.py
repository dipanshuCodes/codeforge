from solution import word_count


def test_counts():
    assert word_count("the cat and the hat") == {"the": 2, "cat": 1, "and": 1, "hat": 1}


def test_extra_whitespace():
    assert word_count("  a   a\tb\n") == {"a": 2, "b": 1}


def test_empty():
    assert word_count("") == {}
