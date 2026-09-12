"""Idempotent bootstrap of the RBAC catalog and the initial admin account.

This seeds *configuration* (the fixed set of roles and permissions from
app.core.rbac) and, if configured, creates ONE real administrator account from
environment variables. It creates no sample/fake domain data — no documents,
events, sources, or map points. Running it repeatedly is safe.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.rbac import PERMISSIONS, ROLES
from app.core.security import hash_password
from app.db.session import dispose_engine, get_sessionmaker
from app.models.iam import Permission, Role, User

log = get_logger("bootstrap")


async def seed_permissions(db: AsyncSession) -> dict[str, Permission]:
    existing = {p.code: p for p in (await db.execute(select(Permission))).scalars()}
    for code, desc in PERMISSIONS.items():
        if code in existing:
            if existing[code].description != desc:
                existing[code].description = desc
        else:
            p = Permission(code=code, description=desc)
            db.add(p)
            existing[code] = p
    await db.flush()
    return existing


async def seed_roles(db: AsyncSession, perms: dict[str, Permission]) -> None:
    existing = {r.name: r for r in (await db.execute(select(Role))).scalars()}
    for name, (desc, codes) in ROLES.items():
        role = existing.get(name)
        if role is None:
            role = Role(name=name, description=desc)
            db.add(role)
            existing[name] = role
        else:
            role.description = desc
        role.permissions = [perms[c] for c in sorted(codes)]
    await db.flush()


async def ensure_admin(db: AsyncSession) -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        log.info("bootstrap_admin_skipped", reason="no IS_BOOTSTRAP_ADMIN_* set")
        return

    from app.core.passwords import PasswordPolicyError, validate_password

    try:
        validate_password(s.bootstrap_admin_password)
    except PasswordPolicyError as exc:
        if s.environment == "production":
            raise RuntimeError(f"Bootstrap admin password fails policy: {exc}") from exc
        log.warning("bootstrap_admin_weak_password", detail=str(exc))

    email = s.bootstrap_admin_email.lower()
    found = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if found is not None:
        found.hashed_password = hash_password(s.bootstrap_admin_password)
        found.full_name = s.bootstrap_admin_name
        found.clearance_level = 5
        found.is_active = True
        found.roles = [(
            await db.execute(select(Role).where(Role.name == "admin"))
        ).scalar_one()]
        log.info("bootstrap_admin_password_updated", email=email)
        return
    admin_role = (
        await db.execute(select(Role).where(Role.name == "admin"))
    ).scalar_one()
    user = User(
        email=email,
        hashed_password=hash_password(s.bootstrap_admin_password),
        full_name=s.bootstrap_admin_name,
        clearance_level=5,
        is_active=True,
        roles=[admin_role],
    )
    db.add(user)
    log.info("bootstrap_admin_created", email=email)


async def run_bootstrap() -> None:
    async with get_sessionmaker()() as db:
        perms = await seed_permissions(db)
        await seed_roles(db, perms)
        await ensure_admin(db)
        await db.commit()
    log.info("bootstrap_complete", permissions=len(PERMISSIONS), roles=len(ROLES))


async def _main_async() -> None:
    # Dispose the engine inside the SAME event loop that created it, otherwise
    # cleanup runs against a closed loop.
    try:
        await run_bootstrap()
    finally:
        await dispose_engine()


def main() -> None:
    s = get_settings()
    configure_logging(level=s.log_level, json_output=s.log_json)
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
