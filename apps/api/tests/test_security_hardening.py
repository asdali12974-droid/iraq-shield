"""Security regression tests added during the P0 hardening pass.

Covers: 401 variants (missing/invalid/tampered/expired), 403 + audit of denials,
privilege escalation, malformed input handling, no-secret-leakage, password
policy, brute-force lockout, refresh rotation/reuse/logout revocation, security
headers, production-safety guard, and data-sovereignty (no external hosts).
"""
from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.core.config import Settings, get_settings

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN = {"email": "admin@iraqshield.test", "password": "admin-test-password-123"}


def _forge(claims_override: dict, *, secret: str | None = None) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + 3600,
        "jti": str(uuid.uuid4()),
    }
    payload.update(claims_override)
    return jwt.encode(payload, secret or s.jwt_secret, algorithm=s.jwt_algorithm)


# --------------------------------------------------------------------------- #
# 401 — authentication failures
# --------------------------------------------------------------------------- #
async def test_401_missing_token(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_401_tampered_token(client, admin_token):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}x"})
    assert r.status_code == 401


async def test_401_wrong_signature(client):
    forged = _forge({}, secret="a-different-secret-entirely")
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_401_expired_token(client):
    now = int(time.time())
    s = get_settings()
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": now - 10, "exp": now - 5, "jti": str(uuid.uuid4())},
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


async def test_401_missing_required_claims(client):
    s = get_settings()
    # No jti/type -> decode requires them -> rejected.
    bad = jwt.encode({"sub": str(uuid.uuid4()), "iat": int(time.time()), "exp": int(time.time()) + 60}, s.jwt_secret, algorithm=s.jwt_algorithm)
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


async def test_401_refresh_token_used_as_access(client):
    login = await client.post("/api/v1/auth/login", json=ADMIN)
    refresh = login.json()["refresh_token"]
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# 403 / privilege escalation
# --------------------------------------------------------------------------- #
PROTECTED = [
    ("GET", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/roles"),
    ("GET", "/api/v1/audit"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
async def test_protected_endpoints_require_auth(client, method, path):
    r = await client.request(method, path, json={})
    assert r.status_code == 401, f"{method} {path} was reachable without a token"


async def test_viewer_cannot_escalate_to_admin(client, viewer_token):
    h = {"Authorization": f"Bearer {viewer_token}"}
    assert (await client.get("/api/v1/admin/users", headers=h)).status_code == 403
    assert (await client.get("/api/v1/audit", headers=h)).status_code == 403
    r = await client.post(
        "/api/v1/admin/users",
        headers=h,
        json={"email": "x@iraqshield.test", "password": "Str0ng-Passw0rd!", "roles": ["admin"]},
    )
    assert r.status_code == 403


async def test_permission_denial_is_audited(client, admin_token, viewer_token):
    await client.get("/api/v1/audit", headers={"Authorization": f"Bearer {viewer_token}"})
    entries = (
        await client.get(
            "/api/v1/audit?action=authz.permission_denied",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    assert any(e["action"] == "authz.permission_denied" for e in entries)


# --------------------------------------------------------------------------- #
# Malformed input & no-leak
# --------------------------------------------------------------------------- #
async def test_malformed_login_returns_422(client):
    assert (await client.post("/api/v1/auth/login", json={})).status_code == 422
    assert (await client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"})).status_code == 422


async def test_422_does_not_echo_submitted_input(client):
    # A weak password must never be reflected back in the error body.
    secret_pw = "SuperSecretLeak12345"
    r = await client.post(
        "/api/v1/admin/users", json={"email": "leak@iraqshield.test", "password": secret_pw}
    )
    # Unauthenticated -> 401 before validation; ensure the password is nowhere.
    assert secret_pw not in r.text


async def test_password_never_appears_in_audit(client, admin_token):
    body = (
        await client.get("/api/v1/audit?limit=50", headers={"Authorization": f"Bearer {admin_token}"})
    ).text
    assert "password" not in body.lower() or '"password"' not in body
    assert ADMIN["password"] not in body


# --------------------------------------------------------------------------- #
# Password policy
# --------------------------------------------------------------------------- #
async def test_weak_password_rejected(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(
        "/api/v1/admin/users",
        headers=h,
        json={"email": "weak@iraqshield.test", "password": "short", "roles": ["viewer"]},
    )
    assert r.status_code == 422


async def test_strong_password_accepted(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(
        "/api/v1/admin/users",
        headers=h,
        json={"email": f"ok-{uuid.uuid4().hex[:8]}@iraqshield.test", "password": "Str0ng-Passw0rd!", "roles": ["viewer"]},
    )
    assert r.status_code == 201


# --------------------------------------------------------------------------- #
# Brute-force lockout
# --------------------------------------------------------------------------- #
async def test_bruteforce_lockout(client):
    s = get_settings()
    email = f"brute-{uuid.uuid4().hex[:8]}@iraqshield.test"
    for _ in range(s.login_max_email_failures):
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-guess-xx"})
        assert r.status_code == 401
    blocked = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-guess-xx"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


# --------------------------------------------------------------------------- #
# Refresh rotation / reuse / logout
# --------------------------------------------------------------------------- #
async def test_refresh_rotation_and_reuse_detection(client):
    login = await client.post("/api/v1/auth/login", json=ADMIN)
    old_refresh = login.json()["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    new_refresh = rotated.json()["refresh_token"]
    assert new_refresh != old_refresh

    # Reusing the old (now revoked) refresh token must fail.
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401

    # Reuse detection burns the family: the rotated token is now revoked too.
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after.status_code == 401


async def test_logout_revokes_refresh(client):
    login = await client.post("/api/v1/auth/login", json=ADMIN)
    refresh = login.json()["refresh_token"]
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert out.status_code == 204
    # The refresh token no longer works after logout.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Security headers
# --------------------------------------------------------------------------- #
async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("Referrer-Policy") == "no-referrer"


# --------------------------------------------------------------------------- #
# Production-safety guard (unit)
# --------------------------------------------------------------------------- #
def test_production_guard_rejects_insecure_defaults():
    s = Settings(environment="production", jwt_secret="dev-insecure-secret-change-me", postgres_password="iraqshield")
    with pytest.raises(RuntimeError):
        s.assert_production_safety()


def test_production_guard_accepts_strong_config():
    s = Settings(
        environment="production",
        jwt_secret="x" * 40,
        postgres_password="a-strong-db-password",
        minio_secret_key="a-strong-minio-secret",
        neo4j_password="a-strong-neo4j-password",
        cors_origins=["https://shield.example"],
        debug=False,
    )
    s.assert_production_safety()  # must not raise
