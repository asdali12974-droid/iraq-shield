"""End-to-end auth + RBAC + audit tests against the real database."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN_EMAIL = "admin@iraqshield.test"
ADMIN_PASS = "admin-test-password-123"


async def test_login_success_and_me(client, admin_token):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    me = resp.json()
    assert me["email"] == ADMIN_EMAIL
    assert "admin" in me["role_names"]
    assert "admin:users:read" in me["permission_codes"]


async def test_login_wrong_password(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "definitely-wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_login_unknown_user(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@iraqshield.test", "password": "whatever12345"},
    )
    assert resp.status_code == 401


async def test_refresh_flow(client):
    login = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}
    )
    refresh_token = login.json()["refresh_token"]
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_refresh_rejects_access_token(client, admin_token):
    # An access token must not be usable as a refresh token.
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": admin_token}
    )
    assert resp.status_code == 401


async def test_protected_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_rbac_admin_can_list_users(client, admin_token):
    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_rbac_viewer_forbidden_on_admin(client, viewer_token):
    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {viewer_token}"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


async def test_audit_records_login(client, admin_token):
    # Trigger a fresh failed login, then confirm it is in the audit log.
    await client.post(
        "/api/v1/auth/login",
        json={"email": "audit-probe@iraqshield.test", "password": "bad-password-xx"},
    )
    resp = await client.get(
        "/api/v1/audit?action=auth.login.failure",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert any(
        e["actor_email"] == "audit-probe@iraqshield.test" for e in entries
    ), "failed login was not audited"
    assert all(e["outcome"] == "failure" for e in entries)


async def test_audit_requires_permission(client, viewer_token):
    resp = await client.get(
        "/api/v1/audit", headers={"Authorization": f"Bearer {viewer_token}"}
    )
    assert resp.status_code == 403
