"""Password policy — enforced on every password the system accepts."""
from __future__ import annotations

import re

MIN_LENGTH = 12

# Tiny denylist of obviously weak choices. Not a substitute for length/entropy,
# just a guard against the most common values.
_COMMON = frozenset(
    {
        "password", "password1", "password123", "12345678", "123456789",
        "qwertyuiop", "adminadmin", "iraqshield", "changeme", "letmein12345",
        "administrator",
    }
)

_CLASSES = (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")


class PasswordPolicyError(ValueError):
    """Raised when a password does not meet policy."""


def validate_password(pw: str) -> str:
    problems: list[str] = []
    if len(pw) < MIN_LENGTH:
        problems.append(f"be at least {MIN_LENGTH} characters")
    classes = sum(bool(re.search(p, pw)) for p in _CLASSES)
    if classes < 3:
        problems.append("include at least 3 of: lowercase, uppercase, digit, symbol")
    if re.search(r"(.)\1\1", pw):
        problems.append("not repeat a character 3+ times in a row")
    if pw.lower() in _COMMON:
        problems.append("not be a common/guessable password")
    if problems:
        raise PasswordPolicyError("Password must " + "; ".join(problems) + ".")
    return pw
