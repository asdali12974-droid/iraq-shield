"""Unit tests for the cryptographic core — no DB or services required."""
from __future__ import annotations

import time

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert h.startswith("$argon2")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False


def test_password_hash_is_salted():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b  # unique salt per hash


def test_verify_rejects_garbage_hash():
    assert verify_password("x", "not-a-real-hash") is False


def test_access_token_roundtrip():
    tok = create_access_token("user-123", extra={"email": "a@b.c"})
    claims = decode_token(tok, expected_type="access")
    assert claims["sub"] == "user-123"
    assert claims["type"] == "access"
    assert claims["email"] == "a@b.c"
    assert "jti" in claims


def test_token_type_enforced():
    refresh = create_refresh_token("user-123")
    with pytest.raises(TokenError):
        decode_token(refresh, expected_type="access")


def test_tampered_token_rejected():
    tok = create_access_token("user-123")
    with pytest.raises(TokenError):
        decode_token(tok + "tamper", expected_type="access")


def test_expired_token_rejected(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "access_token_ttl_minutes", 0)
    # ttl of 0 minutes => exp == iat; sleep to ensure it is in the past.
    tok = create_access_token("user-123")
    time.sleep(1)
    with pytest.raises(TokenError):
        decode_token(tok, expected_type="access")
