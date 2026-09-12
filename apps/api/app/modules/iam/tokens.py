"""Refresh-token lifecycle: issue, rotate, revoke.

Refresh tokens are persisted by jti so they can be revoked. Rotation issues a
new token and revokes the old one; presenting an already-revoked token is
treated as reuse (possible theft) and revokes the user's entire token family.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, create_refresh_token, decode_token
from app.models.auth import RefreshToken
from app.models.iam import User


class RefreshError(Exception):
    """Raised for any invalid/expired/revoked/reused refresh token."""


async def issue_refresh(
    db: AsyncSession, user: User, *, ip: str | None = None, ua: str | None = None
) -> str:
    issued = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            id=uuid.UUID(issued.jti),
            user_id=user.id,
            expires_at=issued.expires_at,
            ip_address=ip,
            user_agent=(ua or None),
        )
    )
    await db.flush()
    return issued.token


async def _lookup(db: AsyncSession, token: str) -> tuple[dict, RefreshToken | None]:
    claims = decode_token(token, expected_type="refresh")
    jti = uuid.UUID(claims["jti"])
    return claims, await db.get(RefreshToken, jti)


async def rotate_refresh(
    db: AsyncSession, token: str, *, ip: str | None = None, ua: str | None = None
) -> tuple[User, str]:
    try:
        _, row = await _lookup(db, token)
    except (TokenError, KeyError, ValueError) as exc:
        raise RefreshError("invalid refresh token") from exc
    if row is None:
        raise RefreshError("unknown refresh token")

    now = datetime.now(UTC)
    if row.revoked_at is not None:
        # Reuse of a revoked token => likely theft. Burn the whole family.
        await revoke_all_for_user(db, row.user_id)
        raise RefreshError("refresh token reuse detected")
    if row.expires_at <= now:
        raise RefreshError("refresh token expired")

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise RefreshError("user not found or inactive")

    new = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            id=uuid.UUID(new.jti),
            user_id=user.id,
            expires_at=new.expires_at,
            ip_address=ip,
            user_agent=(ua or None),
        )
    )
    row.revoked_at = now
    row.replaced_by = uuid.UUID(new.jti)
    await db.flush()
    return user, new.token


async def revoke_refresh(db: AsyncSession, token: str) -> bool:
    try:
        _, row = await _lookup(db, token)
    except (TokenError, KeyError, ValueError):
        return False
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await db.flush()
        return True
    return False


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.flush()
