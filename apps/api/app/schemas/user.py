"""User schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.passwords import validate_password
from app.schemas.common import EmailLike


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    clearance_level: int
    role_names: list[str]
    permission_codes: list[str]
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailLike
    password: str = Field(max_length=256)
    full_name: str = Field(default="", max_length=200)
    clearance_level: int = Field(default=0, ge=0, le=5)
    roles: list[str] = Field(default_factory=list)

    @field_validator("password")
    @classmethod
    def _policy(cls, v: str) -> str:
        return validate_password(v)


class UserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    clearance_level: int
    role_names: list[str]
    created_at: datetime
