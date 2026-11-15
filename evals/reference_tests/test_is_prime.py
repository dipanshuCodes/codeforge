from solution import is_prime


def test_primes():
    assert all(is_prime(n) for n in (2, 3, 5, 7, 13, 97))


def test_not_primes():
    assert not any(is_prime(n) for n in (0, 1, 4, 9, 15, 100))


def test_negative():
    assert not is_prime(-7)
