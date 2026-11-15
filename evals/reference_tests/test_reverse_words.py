from solution import reverse_words


def test_basic():
    assert reverse_words("hello big world") == "world big hello"


def test_single_word():
    assert reverse_words("hello") == "hello"


def test_extra_spaces_collapse():
    assert reverse_words("  a   b  ") == "b a"
