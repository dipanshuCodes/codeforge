from solution import count_vowels


def test_lowercase():
    assert count_vowels("banana") == 3


def test_mixed_case():
    assert count_vowels("AEIOU xyz") == 5


def test_none():
    assert count_vowels("rhythm") == 0
