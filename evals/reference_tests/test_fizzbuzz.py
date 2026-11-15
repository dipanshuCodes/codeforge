from solution import fizzbuzz


def test_fifteen():
    assert fizzbuzz(15) == ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz",
                            "11", "Fizz", "13", "14", "FizzBuzz"]


def test_zero_is_empty():
    assert fizzbuzz(0) == []
