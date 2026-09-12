"""User & RBAC service layer."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password, verify_password
from app.models.iam import Permission, Role, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == email.lower()))
    return res.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """Return the user iff credentials are valid and the account is active.

    Runs a hash verification even when the user does not exist, to keep the
    response time uniform and avoid a user-enumeration timing side channel.
    """
    user = await get_user_by_email(db, email)
    if user is None:
        # Dummy verify against a throwaway hash to equalize timing.
        verify_password(password, hash_password("timing-equalizer"))
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str = "",
    clearance_level: int = 0,
    role_names: list[str] | None = None,
) -> User:
    email = email.lower()
    if await get_user_by_email(db, email) is not None:
        raise ConflictError(f"A user with email {email} already exists")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        clearance_level=clearance_level,
    )
    if role_names:
        roles = await _resolve_roles(db, role_names)
        user.roles = roles
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _resolve_roles(db: AsyncSession, names: list[str]) -> list[Role]:
    res = await db.execute(select(Role).where(Role.name.in_(names)))
    found = list(res.scalars().all())
    found_names = {r.name for r in found}
    missing = set(names) - found_names
    if missing:
        raise NotFoundError(f"Unknown role(s): {', '.join(sorted(missing))}")
    return found


async def list_users(db: AsyncSession, limit: int = 100, offset: int = 0) -> list[User]:
    res = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    return list(res.scalars().all())


async def list_permissions(db: AsyncSession) -> list[Permission]:
    res = await db.execute(select(Permission).order_by(Permission.code))
    return list(res.scalars().all())
