"""Audit writing service. Append-only by contract."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.audit import AuditLog

log = get_logger("audit")


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    """Record a sensitive action. Never raises into the caller's flow —
    an audit failure is logged but must not break the audited operation."""
    entry = AuditLog(
        action=action,
        actor_id=actor_id,
        actor_email=actor_email,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:512] or None,
        details=details or {},
    )
    try:
        db.add(entry)
        if commit:
            await db.commit()
        else:
            await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.error("audit_write_failed", action=action, error=str(exc))
        await db.rollback()
    return entry
