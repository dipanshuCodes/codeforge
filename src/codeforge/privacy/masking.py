"""Masking at ingress (security invariant 1). Pure functions, no I/O.

Masks run in the agreed order so a broader digit pattern never eats a narrower one first:
[SECRET], [EMAIL], [CARD] (Luhn), [AADHAAR], [PHONE].
"""

from __future__ import annotations

import re

_SECRET = re.compile(r"(?<![A-Za-z0-9_-])(?:sk-|gsk_)[A-Za-z0-9_-]{16,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 13–19 digits, optionally grouped by single spaces or dashes; kept only if Luhn passes.
_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
# No checksum on purpose: any 12-digit number starting 2–9 is masked (fails closed).
# Not right after "+", so "+91" plus a 10-digit phone stays a [PHONE].
_AADHAAR = re.compile(r"(?<![\d+])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PHONE = re.compile(r"(?<![\d+])(?:\+91[ -]?|0)?[6-9]\d{9}(?!\d)")


def luhn_valid(digits: str) -> bool:
    """Luhn checksum over a string of digits."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    digits = re.sub(r"[ -]", "", match.group())
    return "[CARD]" if luhn_valid(digits) else match.group()


def mask(text: str) -> str:
    """Replace secrets and PII with placeholders. Idempotent."""
    text = _SECRET.sub("[SECRET]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _CARD.sub(_card, text)
    text = _AADHAAR.sub("[AADHAAR]", text)
    return _PHONE.sub("[PHONE]", text)
