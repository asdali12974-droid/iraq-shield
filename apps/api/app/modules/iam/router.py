"""Auth & IAM HTTP endpoints."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AuthError, RateLimitedError
from app.core.security import create_access_token, decode_token
from app.db.session import get_db
from app.models.iam import User
from app.modules.audit.service import write_audit
from app.modules.iam import service, throttle, tokens
from app.modules.iam.deps import get_current_user, require_permission
from app.modules.iam.tokens import RefreshError
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair
from app.schemas.user import UserCreate, UserListItem, UserPublic

router = APIRouter()


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _pair(user: User, refresh_token: str) -> TokenPair:
    s = get_settings()
    access = create_access_token(
        str(user.id), extra={"email": user.email, "roles": user.role_names}
    )
    return TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=s.access_token_ttl_minutes * 60,
    )


@router.post("/auth/login", response_model=TokenPair, tags=["auth"])
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip, ua = _client(request)

    # Brute-force throttle: refuse if this email/IP is locked out.
    state = await throttle.check(payload.email, ip)
    if state.locked:
        await write_audit(
            db,
            action="auth.login.blocked",
            actor_email=payload.email.lower(),
            outcome="failure",
            ip_address=ip,
            user_agent=ua,
            details={"retry_after": state.retry_after},
            commit=True,
        )
        raise RateLimitedError(
            "Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(state.retry_after)},
        )

    user = await service.authenticate(db, payload.email, payload.password)
    if user is None:
        await throttle.register_failure(payload.email, ip)
        await write_audit(
            db,
            action="auth.login.failure",
            actor_email=payload.email.lower(),
            outcome="failure",
            ip_address=ip,
            user_agent=ua,
            commit=True,
        )
        raise AuthError("Invalid email or password")

    await throttle.reset(payload.email, ip)
    user.last_login_at = datetime.now(tz=UTC)
    refresh_token = await tokens.issue_refresh(db, user, ip=ip, ua=ua)
    await write_audit(
        db,
        action="auth.login.success",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=ip,
        user_agent=ua,
        commit=True,
    )
    return _pair(user, refresh_token)


@router.post("/auth/refresh", response_model=TokenPair, tags=["auth"])
async def refresh(payload: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip, ua = _client(request)
    try:
        user, new_refresh = await tokens.rotate_refresh(db, payload.refresh_token, ip=ip, ua=ua)
    except RefreshError as exc:
        await write_audit(
            db,
            action="auth.refresh.failure",
            outcome="failure",
            ip_address=ip,
            user_agent=ua,
            details={"reason": str(exc)},
            commit=True,
        )
        raise AuthError("Invalid or expired refresh token") from exc

    await write_audit(
        db,
        action="auth.refresh.success",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=ip,
        user_agent=ua,
        commit=True,
    )
    return _pair(user, new_refresh)


@router.post("/auth/logout", status_code=204, tags=["auth"])
async def logout(payload: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip, ua = _client(request)
    revoked = await tokens.revoke_refresh(db, payload.refresh_token)
    actor_id: uuid.UUID | None = None
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        actor_id = uuid.UUID(claims["sub"])
    except Exception:  # noqa: BLE001 — logout must be best-effort
        actor_id = None
    await write_audit(
        db,
        action="auth.logout",
        actor_id=actor_id,
        outcome="success" if revoked else "failure",
        ip_address=ip,
        user_agent=ua,
        commit=True,
    )
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserPublic, tags=["auth"])
async def me(user: User = Depends(get_current_user)):
    return UserPublic.model_validate(user)


@router.get("/admin/users", response_model=list[UserListItem], tags=["admin"])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("admin:users:read")),
    limit: int = 100,
    offset: int = 0,
):
    users = await service.list_users(db, limit=limit, offset=offset)
    return [UserListItem.model_validate(u) for u in users]


@router.post("/admin/users", response_model=UserPublic, status_code=201, tags=["admin"])
async def create_user(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("admin:users:manage")),
):
    user = await service.create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        clearance_level=payload.clearance_level,
        role_names=payload.roles,
    )
    ip, ua = _client(request)
    await write_audit(
        db,
        action="admin.user.create",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="user",
        resource_id=str(user.id),
        ip_address=ip,
        user_agent=ua,
        details={"email": user.email, "roles": user.role_names},
    )
    return UserPublic.model_validate(user)


@router.get("/admin/roles", tags=["admin"])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("admin:roles:read")),
):
    from sqlalchemy import select

    from app.models.iam import Role

    res = await db.execute(select(Role).order_by(Role.name))
    roles = res.scalars().all()
    return [
        {
            "name": r.name,
            "description": r.description,
            "permissions": sorted(p.code for p in r.permissions),
        }
        for r in roles
    ]
