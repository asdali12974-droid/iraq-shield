"""Password hashing (Argon2id) and JWT issuing/verification.

This is the real cryptographic core of P0 authentication. Keycloak/OIDC can be
layered on top later (P10) without touching call sites, because everything here
is behind small functions the rest of the app depends on.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with sane library defaults


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _encode(
    subject: str,
    token_type: str,
    ttl: timedelta,
    extra: dict[str, Any] | None = None,
) -> IssuedToken:
    s = get_settings()
    issued = _now()
    expires_at = issued + ttl
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(issued.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
    return IssuedToken(token=token, jti=jti, expires_at=expires_at)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    return _encode(
        subject, "access", timedelta(minutes=s.access_token_ttl_minutes), extra
    ).token


def create_refresh_token(subject: str) -> IssuedToken:
    """Returns the token plus its jti and expiry so the caller can persist it."""
    s = get_settings()
    return _encode(subject, "refresh", timedelta(days=s.refresh_token_ttl_days))


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "type", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if expected_type and payload.get("type") != expected_type:
        raise TokenError(
            f"wrong token type: expected {expected_type}, got {payload.get('type')}"
        )
    return payload
