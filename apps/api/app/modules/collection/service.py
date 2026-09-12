"""Source registry service layer."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.ssrf import SSRFError, validate_url_shallow
from app.models.collection import (
    ArchiveEntity,
    CollectionRun,
    ContentRelation,
    Entity,
    EntityRelationship,
    Event,
    EventArchive,
    EventEntity,
    RawArchive,
    Source,
)
from app.modules.collection.base import registered_types


class UnsupportedSourceType(AppError):
    status_code = 400
    code = "unsupported_source_type"


async def create_source(db: AsyncSession, data: dict) -> Source:
    # Reject obvious SSRF targets at input; strict guard runs again at fetch time.
    try:
        validate_url_shallow(data["url"])
    except SSRFError as exc:
        raise AppError(str(exc), code="ssrf_rejected", status_code=400) from exc

    # A source can only be created for an implemented collector.
    if data["source_type"] not in registered_types():
        raise UnsupportedSourceType(
            f"no collector implemented for source_type '{data['source_type']}' yet"
        )

    existing = await db.execute(select(Source).where(Source.url == data["url"]))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"a source with url {data['url']} already exists")

    # Telegram sources start unverified — never claim verification without a real
    # channel resolve (MTProto) or HTTP page check (web).
    if data["source_type"] in ("TELEGRAM_PUBLIC", "TELEGRAM_PUBLIC_WEB"):
        data.setdefault("verification_status", "pending")

    source = Source(**data)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def get_source(db: AsyncSession, source_id: uuid.UUID) -> Source:
    src = await db.get(Source, source_id)
    if src is None:
        raise NotFoundError("source not found")
    return src


async def list_sources(db: AsyncSession, limit: int = 200, offset: int = 0) -> list[Source]:
    res = await db.execute(
        select(Source).order_by(Source.created_at.desc()).limit(limit).offset(offset)
    )
    return list(res.scalars().all())


async def update_source(db: AsyncSession, source: Source, changes: dict) -> Source:
    for key, value in changes.items():
        if value is not None:
            setattr(source, key, value)
    await db.commit()
    await db.refresh(source)
    return source


async def set_enabled(db: AsyncSession, source: Source, enabled: bool) -> Source:
    source.enabled = enabled
    await db.commit()
    await db.refresh(source)
    return source


async def list_runs(
    db: AsyncSession, source_id: uuid.UUID, limit: int = 50
) -> list[CollectionRun]:
    res = await db.execute(
        select(CollectionRun)
        .where(CollectionRun.source_id == source_id)
        .order_by(CollectionRun.started_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def list_archive(
    db: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    current_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[RawArchive]:
    stmt = select(RawArchive)
    if source_id is not None:
        stmt = stmt.where(RawArchive.source_id == source_id)
    if current_only:
        stmt = stmt.where(RawArchive.is_current.is_(True))
    stmt = stmt.order_by(RawArchive.collected_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def search_archive(
    db: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    language: str | None = None,
    author: str | None = None,
    content_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> list[RawArchive]:
    """Search archive items with optional filters.

    Args:
        source_id: Filter by source
        language: Filter by language code
        author: Filter by author (exact match)
        content_type: Filter by content type
        date_from: Filter items collected on/after ISO8601 date
        date_to: Filter items collected on/before ISO8601 date
        limit: Max results (capped at 500)

    Returns:
        List of current archive items matching filters, ordered by collected_at DESC
    """
    from datetime import datetime

    # Cap limit at 500 for safety
    limit = min(int(limit), 500)

    stmt = select(RawArchive).where(RawArchive.is_current.is_(True))

    if source_id is not None:
        stmt = stmt.where(RawArchive.source_id == source_id)

    if language is not None:
        stmt = stmt.where(RawArchive.language == language)

    if author is not None:
        stmt = stmt.where(RawArchive.author == author)

    if content_type is not None:
        stmt = stmt.where(RawArchive.content_type == content_type)

    if date_from is not None:
        try:
            dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            stmt = stmt.where(RawArchive.collected_at >= dt)
        except (ValueError, AttributeError):
            pass  # Silently ignore invalid date format

    if date_to is not None:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            stmt = stmt.where(RawArchive.collected_at <= dt)
        except (ValueError, AttributeError):
            pass  # Silently ignore invalid date format

    stmt = stmt.order_by(RawArchive.collected_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_archive_item(db: AsyncSession, item_id: uuid.UUID) -> RawArchive:
    item = await db.get(RawArchive, item_id)
    if item is None:
        raise NotFoundError("archive item not found")
    return item


async def get_relations(db: AsyncSession, item_id: uuid.UUID) -> list[ContentRelation]:
    from sqlalchemy import or_

    res = await db.execute(
        select(ContentRelation).where(
            or_(
                ContentRelation.from_archive_id == item_id,
                ContentRelation.to_archive_id == item_id,
            )
        )
    )
    return list(res.scalars().all())


async def dashboard_stats(db: AsyncSession) -> dict:
    sources = list((await db.execute(select(Source))).scalars().all())
    counts = {"healthy": 0, "degraded": 0, "failed": 0, "pending": 0}
    active = disabled = 0
    for s in sources:
        if s.enabled:
            active += 1
        else:
            disabled += 1
        h = s.health
        if h in counts:
            counts[h] += 1
    archive_items = (
        await db.execute(select(func.count()).select_from(RawArchive))
    ).scalar_one()
    recent = list(
        (
            await db.execute(
                select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(10)
            )
        ).scalars().all()
    )
    return {
        "total": len(sources),
        "active": active,
        "disabled": disabled,
        "healthy": counts["healthy"],
        "degraded": counts["degraded"],
        "failed": counts["failed"],
        "pending": counts["pending"],
        "archive_items": archive_items,
        "recent_runs": recent,
    }


# --- Events (P1.6) ---
async def create_event(db: AsyncSession, data: dict, created_by: uuid.UUID | None = None) -> Event:
    """Create a new analyst-driven event."""
    event = Event(**data, created_by=created_by, updated_by=created_by)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def get_event(db: AsyncSession, event_id: uuid.UUID) -> Event:
    """Get event by ID."""
    event = await db.get(Event, event_id)
    if event is None:
        raise NotFoundError("event not found")
    return event


async def list_events(
    db: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    status_filter: str | None = None,
    severity_filter: str | None = None,
) -> list[Event]:
    """List events with optional filtering."""
    limit = min(int(limit), 500)
    stmt = select(Event).order_by(Event.created_at.desc())

    if status_filter is not None:
        stmt = stmt.where(Event.status == status_filter)

    if severity_filter is not None:
        stmt = stmt.where(Event.severity == severity_filter)

    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def update_event(
    db: AsyncSession, event: Event, changes: dict, updated_by: uuid.UUID | None = None
) -> Event:
    """Update event fields."""
    for key, value in changes.items():
        if value is not None:
            setattr(event, key, value)
    if updated_by is not None:
        event.updated_by = updated_by
    await db.commit()
    await db.refresh(event)
    return event


async def link_archive_to_event(
    db: AsyncSession, event_id: uuid.UUID, archive_id: uuid.UUID, linked_by: uuid.UUID | None = None
) -> EventArchive:
    """Link an archive item to an event.

    Raises ConflictError if the link already exists.
    Raises NotFoundError if the event or archive item doesn't exist.
    """
    # Verify event exists
    event = await db.get(Event, event_id)
    if event is None:
        raise NotFoundError("event not found")

    # Verify archive item exists and is current
    archive = await db.get(RawArchive, archive_id)
    if archive is None:
        raise NotFoundError("archive item not found")
    if not archive.is_current:
        raise AppError(
            "cannot link non-current archive items",
            code="archive_not_current",
            status_code=400,
        )

    # Check for duplicate link
    existing = await db.execute(
        select(EventArchive).where(
            (EventArchive.event_id == event_id) & (EventArchive.archive_id == archive_id)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("archive item is already linked to this event")

    # Create link
    link = EventArchive(event_id=event_id, archive_id=archive_id, linked_by=linked_by)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def unlink_archive_from_event(
    db: AsyncSession, event_id: uuid.UUID, archive_id: uuid.UUID
) -> None:
    """Remove link between archive item and event."""
    link = await db.execute(
        select(EventArchive).where(
            (EventArchive.event_id == event_id) & (EventArchive.archive_id == archive_id)
        )
    )
    existing = link.scalar_one_or_none()
    if existing is None:
        raise NotFoundError("archive link not found")

    await db.delete(existing)
    await db.commit()


# --- Entities (P1.7) ---
async def create_entity(db: AsyncSession, data: dict, created_by: uuid.UUID | None = None) -> Entity:
    """Create a new analyst-driven entity."""
    entity = Entity(**data, created_by=created_by, updated_by=created_by)
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


async def get_entity(db: AsyncSession, entity_id: uuid.UUID) -> Entity:
    """Get entity by ID."""
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("entity not found")
    return entity


async def list_entities(
    db: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    entity_type: str | None = None,
    status: str | None = None,
) -> list[Entity]:
    """List entities with optional filtering."""
    limit = min(int(limit), 500)
    stmt = select(Entity).order_by(Entity.created_at.desc())

    if entity_type is not None:
        stmt = stmt.where(Entity.entity_type == entity_type)

    if status is not None:
        stmt = stmt.where(Entity.status == status)

    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def update_entity(
    db: AsyncSession, entity: Entity, changes: dict, updated_by: uuid.UUID | None = None
) -> Entity:
    """Update entity fields."""
    for key, value in changes.items():
        if value is not None:
            setattr(entity, key, value)
    if updated_by is not None:
        entity.updated_by = updated_by
    await db.commit()
    await db.refresh(entity)
    return entity


async def link_archive_to_entity(
    db: AsyncSession, entity_id: uuid.UUID, archive_id: uuid.UUID, linked_by: uuid.UUID | None = None
) -> ArchiveEntity:
    """Link an archive item to an entity.

    Raises ConflictError if the link already exists.
    Raises NotFoundError if the entity or archive item doesn't exist.
    """
    # Verify entity exists
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("entity not found")

    # Verify archive item exists and is current
    archive = await db.get(RawArchive, archive_id)
    if archive is None:
        raise NotFoundError("archive item not found")
    if not archive.is_current:
        raise AppError(
            "cannot link non-current archive items",
            code="archive_not_current",
            status_code=400,
        )

    # Check for duplicate link
    existing = await db.execute(
        select(ArchiveEntity).where(
            (ArchiveEntity.entity_id == entity_id) & (ArchiveEntity.archive_id == archive_id)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("archive item is already linked to this entity")

    # Create link
    link = ArchiveEntity(entity_id=entity_id, archive_id=archive_id, linked_by=linked_by)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def unlink_archive_from_entity(
    db: AsyncSession, entity_id: uuid.UUID, archive_id: uuid.UUID
) -> dict:
    """Remove link between archive item and entity.

    Captures link details before deletion for audit purposes.
    Returns the deleted link data.
    """
    link = await db.execute(
        select(ArchiveEntity).where(
            (ArchiveEntity.entity_id == entity_id) & (ArchiveEntity.archive_id == archive_id)
        )
    )
    existing = link.scalar_one_or_none()
    if existing is None:
        raise NotFoundError("archive link not found")

    # Capture details before deletion for audit trail
    link_data = {
        "entity_id": str(existing.entity_id),
        "archive_id": str(existing.archive_id),
        "linked_at": existing.linked_at.isoformat() if existing.linked_at else None,
        "linked_by": str(existing.linked_by) if existing.linked_by else None,
    }

    await db.delete(existing)
    await db.commit()

    return link_data


async def link_entity_to_event(
    db: AsyncSession, entity_id: uuid.UUID, event_id: uuid.UUID, linked_by: uuid.UUID | None = None
) -> EventEntity:
    """Link an entity to an event.

    Raises ConflictError if the link already exists.
    Raises NotFoundError if the entity or event doesn't exist.
    """
    # Verify entity exists
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("entity not found")

    # Verify event exists
    event = await db.get(Event, event_id)
    if event is None:
        raise NotFoundError("event not found")

    # Check for duplicate link
    existing = await db.execute(
        select(EventEntity).where(
            (EventEntity.entity_id == entity_id) & (EventEntity.event_id == event_id)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("entity is already linked to this event")

    # Create link
    link = EventEntity(entity_id=entity_id, event_id=event_id, linked_by=linked_by)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def unlink_entity_from_event(
    db: AsyncSession, entity_id: uuid.UUID, event_id: uuid.UUID
) -> None:
    """Remove link between entity and event."""
    link = await db.execute(
        select(EventEntity).where(
            (EventEntity.entity_id == entity_id) & (EventEntity.event_id == event_id)
        )
    )
    existing = link.scalar_one_or_none()
    if existing is None:
        raise NotFoundError("event link not found")

    await db.delete(existing)
    await db.commit()


async def create_relationship(
    db: AsyncSession,
    from_entity_id: uuid.UUID,
    to_entity_id: uuid.UUID,
    relation_type: str,
    confidence: float = 0.5,
    created_by: uuid.UUID | None = None,
) -> EntityRelationship:
    """Create a relationship between two entities.

    Raises NotFoundError if either entity doesn't exist.
    Raises ConflictError if the relationship already exists.
    """
    # Verify both entities exist
    from_entity = await db.get(Entity, from_entity_id)
    if from_entity is None:
        raise NotFoundError("from_entity not found")

    to_entity = await db.get(Entity, to_entity_id)
    if to_entity is None:
        raise NotFoundError("to_entity not found")

    # Check for duplicate relationship (unique constraint on from/to/type)
    existing = await db.execute(
        select(EntityRelationship).where(
            (EntityRelationship.from_entity_id == from_entity_id)
            & (EntityRelationship.to_entity_id == to_entity_id)
            & (EntityRelationship.relation_type == relation_type)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("relationship already exists between these entities with this type")

    # Create relationship
    rel = EntityRelationship(
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relation_type=relation_type,
        confidence=confidence,
        created_by=created_by,
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return rel


async def delete_relationship(db: AsyncSession, relationship_id: uuid.UUID) -> dict:
    """Delete a relationship (hard delete).

    Captures all relationship details before deletion for audit purposes.
    Returns the deleted relationship data.
    """
    rel = await db.get(EntityRelationship, relationship_id)
    if rel is None:
        raise NotFoundError("relationship not found")

    # Capture details before deletion
    rel_data = {
        "id": str(rel.id),
        "from_entity_id": str(rel.from_entity_id),
        "to_entity_id": str(rel.to_entity_id),
        "relation_type": rel.relation_type,
        "confidence": rel.confidence,
        "created_by": str(rel.created_by) if rel.created_by else None,
        "created_at": rel.created_at.isoformat() if rel.created_at else None,
    }

    await db.delete(rel)
    await db.commit()

    return rel_data


async def get_entity_relationships(
    db: AsyncSession, entity_id: uuid.UUID
) -> tuple[list[EntityRelationship], list[EntityRelationship]]:
    """Get outgoing and incoming relationships for an entity.

    Returns: (outgoing, incoming)
    """
    # Outgoing: from_entity_id == entity_id
    outgoing_res = await db.execute(
        select(EntityRelationship).where(EntityRelationship.from_entity_id == entity_id)
    )
    outgoing = list(outgoing_res.scalars().all())

    # Incoming: to_entity_id == entity_id
    incoming_res = await db.execute(
        select(EntityRelationship).where(EntityRelationship.to_entity_id == entity_id)
    )
    incoming = list(incoming_res.scalars().all())

    return outgoing, incoming
