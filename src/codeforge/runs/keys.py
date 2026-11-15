"""Run-once keys (security invariant 8). Pure functions.

JSON-encoding the fields before hashing keeps them from running together
("u-ab" + "c" never equals "u-a" + "bc").
"""

from __future__ import annotations

import hashlib
import json


def _key(*fields: str) -> str:
    return hashlib.sha256(json.dumps(fields).encode("utf-8")).hexdigest()


def request_key(user_id: str, masked_request: str) -> str:
    """Identifies a Duplicate Request: same User, same masked text."""
    return _key("request", user_id, masked_request)


def execution_key(user_id: str, code: str, tests: str) -> str:
    """Identifies a repeat Execution: same User, same code and tests."""
    return _key("execution", user_id, code, tests)
