"""Auth request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import EmailLike


class LoginRequest(BaseModel):
    email: EmailLike
    password: str = Field(min_length=1, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime in seconds


class RefreshRequest(BaseModel):
    refresh_token: str
