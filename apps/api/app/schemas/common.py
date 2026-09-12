"""Shared schema helpers."""
from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

# Deliberately permissive: an on-prem intelligence platform commonly uses
# internal email domains (e.g. name@iraqshield.local, name@unit.internal) that
# strict public-deliverability validators reject. We require a sane local@domain
# shape and normalize case, without forbidding reserved/internal TLDs.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("invalid email address")
    return v


EmailLike = Annotated[str, AfterValidator(_normalize_email)]
