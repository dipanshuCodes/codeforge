"""One test per mask, plus numbers that must NOT be masked. All values are fake."""

import pytest

from codeforge.privacy.masking import luhn_valid, mask

FAKE_GROQ = "gsk_" + "A1b2C3d4E5f6G7h8J9k0" * 2
FAKE_OPENAI = "sk-proj-" + "x9Y8z7W6v5U4t3S2"


@pytest.mark.parametrize("key", [FAKE_GROQ, FAKE_OPENAI, "sk-" + "a" * 16])
def test_secret(key):
    assert mask(f"my key is {key} ok") == "my key is [SECRET] ok"


def test_short_sk_prefix_is_not_a_secret():
    assert mask("use sk-learn or gsk_short") == "use sk-learn or gsk_short"


def test_email():
    assert mask("mail student.one+x@example.co.in now") == "mail [EMAIL] now"


@pytest.mark.parametrize("card", ["4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111"])
def test_card_passing_luhn(card):
    assert mask(f"card {card}.") == "card [CARD]."


def test_card_length_digits_failing_luhn_are_kept():
    assert mask("id 4111111111111112") == "id 4111111111111112"


@pytest.mark.parametrize("aadhaar", ["234567890123", "2345 6789 0123", "9999-8888-7777"])
def test_aadhaar(aadhaar):
    assert mask(f"aadhaar {aadhaar}") == "aadhaar [AADHAAR]"


def test_twelve_digits_starting_0_or_1_are_not_aadhaar():
    assert mask("n 123456789012") == "n 123456789012"


@pytest.mark.parametrize("phone", ["9876543210", "+919876543210", "+91 9876543210", "09876543210"])
def test_phone(phone):
    assert mask(f"call {phone} pls") == "call [PHONE] pls"


@pytest.mark.parametrize("text", [
    "2432902008176640000",  # 20! : 19 digits, fails Luhn
    "1234567890",           # 10 digits starting 1: not a phone
    "2024",
    "fibonacci(30)",
    "return sum([1, 2, 3])",
])
def test_must_not_mask(text):
    assert mask(text) == text


def test_student_c_message_masks_key_and_aadhaar():
    text = f"THIS IS NOT WORKING!!! key {FAKE_GROQ} aadhaar 2345 6789 0123 get me a human."
    out = mask(text)
    assert FAKE_GROQ not in out and "2345 6789 0123" not in out
    assert out == "THIS IS NOT WORKING!!! key [SECRET] aadhaar [AADHAAR] get me a human."


def test_mask_is_idempotent():
    once = mask(f"{FAKE_GROQ} a@b.io 4111111111111111 234567890123 9876543210")
    assert mask(once) == once


def test_luhn():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("2432902008176640000")
