"""Authentication & authorization dependencies."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, ForbiddenError
from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models.iam import User
from app.modules.audit.service import write_audit
from app.modules.iam.service import get_user_by_id

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise AuthError("Missing bearer token")
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError("Malformed token subject") from exc

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive")

    # Expose on request state for audit/logging.
    request.state.user_id = str(user.id)
    request.state.user_email = user.email
    return user


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def require_permission(code: str) -> Callable:
    """Dependency factory enforcing that the current user holds `code`.
    A denial is recorded in the audit log."""

    async def _checker(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if code not in user.permission_codes:
            ip, ua = _client(request)
            await write_audit(
                db,
                action="authz.permission_denied",
                actor_id=user.id,
                actor_email=user.email,
                resource_type="permission",
                resource_id=code,
                outcome="failure",
                ip_address=ip,
                user_agent=ua,
                details={"method": request.method, "path": request.url.path},
                commit=True,
            )
            raise ForbiddenError(f"Missing required permission: {code}")
        return user

    return _checker
