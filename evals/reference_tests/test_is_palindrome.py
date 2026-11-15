from solution import is_palindrome


def test_palindromes():
    assert is_palindrome("racecar")
    assert is_palindrome("abba")


def test_not_palindrome():
    assert not is_palindrome("ab")


def test_empty_and_single():
    assert is_palindrome("")
    assert is_palindrome("x")
