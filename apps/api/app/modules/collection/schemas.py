"""Pydantic schemas for the collection API."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.collection import (
    CATEGORIES,
    ENTITY_RELATION_TYPES,
    ENTITY_STATUSES,
    ENTITY_TYPES,
    EVENT_SEVERITIES,
    EVENT_STATUSES,
    RELIABILITY,
    SOURCE_CLASSES,
    SOURCE_TYPES,
)

_COLLECTOR_TYPES = ("RSS",)  # only RSS is implemented in P1.1


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: str
    url: str = Field(min_length=1, max_length=2048)
    language: str | None = Field(default=None, max_length=16)
    country_region: str | None = Field(default=None, max_length=64)
    category: str | None = None
    reliability: str = "C"
    enabled: bool = True
    collection_interval_seconds: int = Field(default=3600, ge=60)
    extraction_config: dict | None = None
    source_class: str | None = None
    telegram_username: str | None = Field(default=None, max_length=64)

    @field_validator("source_class")
    @classmethod
    def _class(cls, v):
        if v is not None and v not in SOURCE_CLASSES:
            raise ValueError(f"source_class must be one of {SOURCE_CLASSES}")
        return v

    @field_validator("source_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {SOURCE_TYPES}")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return v

    @field_validator("reliability")
    @classmethod
    def _rel(cls, v: str) -> str:
        if v not in RELIABILITY:
            raise ValueError(f"reliability must be one of {RELIABILITY}")
        return v


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=16)
    country_region: str | None = Field(default=None, max_length=64)
    category: str | None = None
    reliability: str | None = None
    collection_interval_seconds: int | None = Field(default=None, ge=60)
    extraction_config: dict | None = None
    source_class: str | None = None

    @field_validator("source_class")
    @classmethod
    def _class(cls, v):
        if v is not None and v not in SOURCE_CLASSES:
            raise ValueError(f"source_class must be one of {SOURCE_CLASSES}")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        if v is not None and v not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return v

    @field_validator("reliability")
    @classmethod
    def _rel(cls, v):
        if v is not None and v not in RELIABILITY:
            raise ValueError(f"reliability must be one of {RELIABILITY}")
        return v


class SourcePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: str
    url: str
    language: str | None
    country_region: str | None
    category: str | None
    reliability: str
    enabled: bool
    collection_interval_seconds: int
    health: str
    success_rate: float
    total_runs: int
    success_count: int
    failure_count: int
    consecutive_failures: int
    avg_latency_ms: float
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_status: str | None
    last_error: str | None
    extraction_config: dict | None
    source_class: str | None
    telegram_username: str | None
    telegram_channel_id: int | None
    telegram_title: str | None
    verification_status: str | None
    created_at: datetime


class CollectionRunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    status: str
    http_status: int | None
    items_seen: int
    items_new: int
    items_duplicate: int
    items_versioned: int
    items_discovered: int
    items_failed: int
    latency_ms: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ArchiveItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    url: str
    canonical_url: str | None
    external_id: str | None
    title: str | None
    published_at: datetime | None
    collected_at: datetime
    content_type: str | None
    language: str | None
    author: str | None
    content_hash: str
    fingerprint: str
    version: int
    is_current: bool
    size_bytes: int | None
    raw_ref: str


class RelationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_archive_id: uuid.UUID
    to_archive_id: uuid.UUID
    relation_type: str
    similarity: float
    created_at: datetime


class SourcesDashboard(BaseModel):
    total: int
    active: int
    disabled: int
    healthy: int
    degraded: int
    failed: int
    pending: int
    archive_items: int
    recent_runs: list[CollectionRunPublic]


# --- Events (P1.6) ---
class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4096)
    occurred_at: datetime
    status: str = "pending"
    severity: str = "C"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in EVENT_STATUSES:
            raise ValueError(f"status must be one of {EVENT_STATUSES}")
        return v

    @field_validator("severity")
    @classmethod
    def _severity(cls, v: str) -> str:
        if v not in EVENT_SEVERITIES:
            raise ValueError(f"severity must be one of {EVENT_SEVERITIES}")
        return v


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4096)
    occurred_at: datetime | None = None
    status: str | None = None
    severity: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is not None and v not in EVENT_STATUSES:
            raise ValueError(f"status must be one of {EVENT_STATUSES}")
        return v

    @field_validator("severity")
    @classmethod
    def _severity(cls, v: str | None) -> str | None:
        if v is not None and v not in EVENT_SEVERITIES:
            raise ValueError(f"severity must be one of {EVENT_SEVERITIES}")
        return v


class EventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    occurred_at: datetime
    status: str
    severity: str
    confidence: float
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None


class EventArchivePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    archive_id: uuid.UUID
    linked_at: datetime
    linked_by: uuid.UUID | None


# --- Entities (P1.7) ---
class EntityCreate(BaseModel):
    entity_type: str
    name: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=2048)
    status: str = "pending"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("entity_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {ENTITY_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ENTITY_STATUSES:
            raise ValueError(f"status must be one of {ENTITY_STATUSES}")
        return v


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=2048)
    status: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is not None and v not in ENTITY_STATUSES:
            raise ValueError(f"status must be one of {ENTITY_STATUSES}")
        return v


class EntityPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    name: str
    description: str | None
    status: str
    confidence: float
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None


class ArchiveEntityPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: uuid.UUID
    archive_id: uuid.UUID
    linked_at: datetime
    linked_by: uuid.UUID | None


class EventEntityPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    entity_id: uuid.UUID
    linked_at: datetime
    linked_by: uuid.UUID | None


class EntityRelationshipCreate(BaseModel):
    relation_type: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("relation_type")
    @classmethod
    def _relation_type(cls, v: str) -> str:
        if v not in ENTITY_RELATION_TYPES:
            raise ValueError(f"relation_type must be one of {ENTITY_RELATION_TYPES}")
        return v


class EntityRelationshipPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    relation_type: str
    confidence: float
    created_at: datetime
    created_by: uuid.UUID | None


class EntityRelationshipsResponse(BaseModel):
    """Response containing outgoing and incoming relationships for an entity."""

    outgoing: list[EntityRelationshipPublic]
    incoming: list[EntityRelationshipPublic]
