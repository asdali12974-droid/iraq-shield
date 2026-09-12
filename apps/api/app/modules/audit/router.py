"""Read-only audit log endpoint. Writing is internal only; there is no API to
create, edit, or delete audit entries — by design."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.iam import User
from app.modules.iam.deps import require_permission
from app.schemas.audit import AuditEntry

router = APIRouter()


@router.get("/audit", response_model=list[AuditEntry], tags=["audit"])
async def list_audit(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("audit:read")),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    action: str | None = None,
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return [AuditEntry.model_validate(r) for r in res.scalars().all()]
