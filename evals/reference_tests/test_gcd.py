from solution import gcd


def test_basic():
    assert gcd(12, 18) == 6


def test_coprime():
    assert gcd(17, 5) == 1


def test_with_zero():
    assert gcd(0, 9) == 9
    assert gcd(9, 0) == 9
