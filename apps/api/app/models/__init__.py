"""Model registry — importing this module ensures every table is registered
on the shared Base.metadata (used by Alembic autogenerate)."""
from app.models.audit import AuditLog
from app.models.auth import RefreshToken
from app.models.collection import (
    CollectionRun,
    ContentRelation,
    RawArchive,
    Source,
)
from app.models.iam import Permission, Role, User, role_permissions, user_roles

__all__ = [
    "User",
    "Role",
    "Permission",
    "user_roles",
    "role_permissions",
    "AuditLog",
    "RefreshToken",
    "Source",
    "CollectionRun",
    "RawArchive",
    "ContentRelation",
]
