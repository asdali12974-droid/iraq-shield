"""Collection API: sources, collection jobs, archive, source health.
Every mutating endpoint is RBAC-gated and audited."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.iam import User
from app.modules.audit.service import write_audit
from app.modules.collection import service
from app.modules.collection.runner import run_collection_for_source
from app.modules.collection.schemas import (
    ArchiveEntityPublic,
    ArchiveItemPublic,
    CollectionRunPublic,
    EntityCreate,
    EntityPublic,
    EntityRelationshipCreate,
    EntityRelationshipPublic,
    EntityRelationshipsResponse,
    EntityUpdate,
    EventEntityPublic,
    EventArchivePublic,
    EventCreate,
    EventPublic,
    EventUpdate,
    RelationPublic,
    SourceCreate,
    SourcePublic,
    SourcesDashboard,
    SourceUpdate,
)
from app.modules.collection.storage import get_store
from app.modules.iam.deps import require_permission

router = APIRouter()


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


# --- Sources -------------------------------------------------------------- #
@router.get("/sources", response_model=list[SourcePublic], tags=["collection"])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("sources:read")),
    limit: int = 200,
    offset: int = 0,
):
    return [SourcePublic.model_validate(s) for s in await service.list_sources(db, limit, offset)]


@router.post("/sources", response_model=SourcePublic, status_code=201, tags=["collection"])
async def create_source(
    payload: SourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("sources:manage")),
):
    source = await service.create_source(db, payload.model_dump())
    ip, ua = _client(request)
    await write_audit(
        db, action="source.create", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
        details={"name": source.name, "type": source.source_type, "url": source.url},
    )
    return SourcePublic.model_validate(source)


@router.get("/sources/dashboard", response_model=SourcesDashboard, tags=["collection"])
async def sources_dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("sources:read")),
):
    stats = await service.dashboard_stats(db)
    stats["recent_runs"] = [CollectionRunPublic.model_validate(r) for r in stats["recent_runs"]]
    return SourcesDashboard(**stats)


@router.get("/sources/{source_id}", response_model=SourcePublic, tags=["collection"])
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("sources:read")),
):
    return SourcePublic.model_validate(await service.get_source(db, source_id))


@router.patch("/sources/{source_id}", response_model=SourcePublic, tags=["collection"])
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("sources:manage")),
):
    source = await service.get_source(db, source_id)
    source = await service.update_source(db, source, payload.model_dump(exclude_unset=True))
    ip, ua = _client(request)
    await write_audit(
        db, action="source.update", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
        details=payload.model_dump(exclude_unset=True),
    )
    return SourcePublic.model_validate(source)


@router.post("/sources/{source_id}/enable", response_model=SourcePublic, tags=["collection"])
async def enable_source(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("sources:manage")),
):
    source = await service.set_enabled(db, await service.get_source(db, source_id), True)
    ip, ua = _client(request)
    await write_audit(
        db, action="source.enable", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
    )
    return SourcePublic.model_validate(source)


@router.post("/sources/{source_id}/disable", response_model=SourcePublic, tags=["collection"])
async def disable_source(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("sources:manage")),
):
    source = await service.set_enabled(db, await service.get_source(db, source_id), False)
    ip, ua = _client(request)
    await write_audit(
        db, action="source.disable", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
    )
    return SourcePublic.model_validate(source)


@router.post(
    "/sources/{source_id}/collect", response_model=CollectionRunPublic, tags=["collection"]
)
async def collect_now(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("collection:run")),
):
    source = await service.get_source(db, source_id)
    run = await run_collection_for_source(db, source)
    ip, ua = _client(request)
    await write_audit(
        db, action="collection.run", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
        outcome="success" if run.status == "success" else "failure",
        details={"run_id": str(run.id), "status": run.status,
                 "new": run.items_new, "versioned": run.items_versioned},
    )
    return CollectionRunPublic.model_validate(run)


@router.post("/sources/{source_id}/cancel", status_code=202, tags=["collection"])
async def cancel_source_collection(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("collection:run")),
):
    from app.modules.collection.runner import request_cancel_source

    source = await service.get_source(db, source_id)
    await request_cancel_source(source.id)
    ip, ua = _client(request)
    await write_audit(
        db, action="collection.cancel", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
    )
    return {"status": "cancel_requested", "source_id": str(source.id)}


@router.post("/sources/{source_id}/verify", tags=["collection"])
async def verify_source_endpoint(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("sources:manage")),
):
    source = await service.get_source(db, source_id)

    # Dispatch to the correct verification handler based on source type
    if source.source_type == "TELEGRAM_PUBLIC_WEB":
        from app.modules.collection.telegram_web.verify import verify_source
    else:
        from app.modules.collection.telegram.verify import verify_source

    result = await verify_source(db, source)
    ip, ua = _client(request)
    await write_audit(
        db, action="source.verify", actor_id=actor.id, actor_email=actor.email,
        resource_type="source", resource_id=str(source.id), ip_address=ip, user_agent=ua,
        outcome="success" if result.get("status") == "verified" else "failure",
        details={"status": result.get("status"), "reason": result.get("reason")},
    )
    return result


@router.get(
    "/sources/{source_id}/runs", response_model=list[CollectionRunPublic], tags=["collection"]
)
async def source_runs(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("sources:read")),
    limit: int = 50,
):
    await service.get_source(db, source_id)
    runs = await service.list_runs(db, source_id, limit)
    return [CollectionRunPublic.model_validate(r) for r in runs]


@router.get("/sources/{source_id}/health", tags=["collection"])
async def source_health(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("sources:read")),
):
    s = await service.get_source(db, source_id)
    return {
        "source_id": str(s.id),
        "health": s.health,
        "success_rate": s.success_rate,
        "total_runs": s.total_runs,
        "success_count": s.success_count,
        "failure_count": s.failure_count,
        "consecutive_failures": s.consecutive_failures,
        "avg_latency_ms": s.avg_latency_ms,
        "last_success_at": s.last_success_at,
        "last_failure_at": s.last_failure_at,
        "last_status": s.last_status,
        "last_error": s.last_error,
    }


# --- Archive -------------------------------------------------------------- #
@router.get("/archive", response_model=list[ArchiveItemPublic], tags=["collection"])
async def list_archive(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("archive:read")),
    source_id: uuid.UUID | None = None,
    current_only: bool = True,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
):
    items = await service.list_archive(
        db, source_id=source_id, current_only=current_only, limit=limit, offset=offset
    )
    return [ArchiveItemPublic.model_validate(i) for i in items]


@router.get("/archive/search", response_model=list[ArchiveItemPublic], tags=["collection"])
async def search_archive(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("archive:read")),
    source_id: uuid.UUID | None = None,
    language: str | None = None,
    author: str | None = None,
    content_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Search archive items with optional filters.

    Filters:
    - source_id: UUID of source (optional)
    - language: Language code (optional)
    - author: Author name (optional, exact match)
    - content_type: Content type (optional, e.g., "application/json")
    - date_from: ISO8601 date (optional, inclusive)
    - date_to: ISO8601 date (optional, inclusive)
    - limit: Max results, 1-500 (default 100)

    Returns current versions only, ordered by collected_at DESC.
    """
    items = await service.search_archive(
        db,
        source_id=source_id,
        language=language,
        author=author,
        content_type=content_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return [ArchiveItemPublic.model_validate(i) for i in items]


@router.get("/archive/{item_id}", response_model=ArchiveItemPublic, tags=["collection"])
async def get_archive_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("archive:read")),
):
    return ArchiveItemPublic.model_validate(await service.get_archive_item(db, item_id))


@router.get("/archive/{item_id}/raw", tags=["collection"])
async def get_archive_raw(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("archive:read")),
):
    import asyncio

    item = await service.get_archive_item(db, item_id)
    data = await asyncio.to_thread(get_store().get, item.raw_ref)
    return Response(content=data, media_type=item.content_type or "application/octet-stream")


@router.get("/archive/{item_id}/extracted", tags=["collection"])
async def get_archive_extracted(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("archive:read")),
):
    item = await service.get_archive_item(db, item_id)
    return {
        "id": str(item.id),
        "title": item.title,
        "author": item.author,
        "canonical_url": item.canonical_url,
        "published_at": item.published_at,
        "language": item.language,
        "extracted": item.extracted,
    }


@router.get(
    "/archive/{item_id}/relations", response_model=list[RelationPublic], tags=["collection"]
)
async def get_archive_relations(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("archive:read")),
):
    await service.get_archive_item(db, item_id)
    return [RelationPublic.model_validate(r) for r in await service.get_relations(db, item_id)]


# --- Events (P1.6) -------------------------------------------------------- #
@router.get("/events", response_model=list[EventPublic], tags=["events"])
async def list_events(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("event:read")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    severity: str | None = None,
):
    """List analyst-created events with optional filtering."""
    events = await service.list_events(
        db, limit=limit, offset=offset, status_filter=status, severity_filter=severity
    )
    return [EventPublic.model_validate(e) for e in events]


@router.get("/events/{event_id}", response_model=EventPublic, tags=["events"])
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("event:read")),
):
    """Get a single event by ID."""
    event = await service.get_event(db, event_id)
    return EventPublic.model_validate(event)


@router.post("/events", response_model=EventPublic, status_code=201, tags=["events"])
async def create_event(
    payload: EventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("event:create")),
):
    """Create a new analyst-driven event."""
    event = await service.create_event(db, payload.model_dump(), created_by=actor.id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="event.create",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="event",
        resource_id=str(event.id),
        ip_address=ip,
        user_agent=ua,
        details={
            "title": event.title,
            "status": event.status,
            "severity": event.severity,
            "confidence": event.confidence,
        },
    )
    return EventPublic.model_validate(event)


@router.patch("/events/{event_id}", response_model=EventPublic, tags=["events"])
async def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("event:update")),
):
    """Update an event."""
    event = await service.get_event(db, event_id)
    changes = payload.model_dump(exclude_unset=True)
    event = await service.update_event(db, event, changes, updated_by=actor.id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="event.update",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="event",
        resource_id=str(event.id),
        ip_address=ip,
        user_agent=ua,
        details=changes,
    )
    return EventPublic.model_validate(event)


@router.post(
    "/events/{event_id}/archive/{archive_id}",
    response_model=EventArchivePublic,
    status_code=201,
    tags=["events"],
)
async def link_archive_to_event(
    event_id: uuid.UUID,
    archive_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("event:link")),
):
    """Link an archive item to an event."""
    link = await service.link_archive_to_event(db, event_id, archive_id, linked_by=actor.id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="event.link",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="event_archive",
        resource_id=f"{event_id}:{archive_id}",
        ip_address=ip,
        user_agent=ua,
        details={"event_id": str(event_id), "archive_id": str(archive_id)},
    )
    return EventArchivePublic.model_validate(link)


@router.delete(
    "/events/{event_id}/archive/{archive_id}", status_code=204, tags=["events"]
)
async def unlink_archive_from_event(
    event_id: uuid.UUID,
    archive_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("event:link")),
):
    """Unlink an archive item from an event."""
    await service.unlink_archive_from_event(db, event_id, archive_id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="event.unlink",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="event_archive",
        resource_id=f"{event_id}:{archive_id}",
        ip_address=ip,
        user_agent=ua,
        details={"event_id": str(event_id), "archive_id": str(archive_id)},
    )


# --- Entities (P1.7) -------------------------------------------------------- #
@router.get("/entities", response_model=list[EntityPublic], tags=["entities"])
async def list_entities(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("entity:read")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    entity_type: str | None = None,
    status: str | None = None,
):
    """List analyst-created entities with optional filtering."""
    entities = await service.list_entities(
        db, limit=limit, offset=offset, entity_type=entity_type, status=status
    )
    return [EntityPublic.model_validate(e) for e in entities]


@router.get("/entities/{entity_id}", response_model=EntityPublic, tags=["entities"])
async def get_entity(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("entity:read")),
):
    """Get a single entity by ID."""
    entity = await service.get_entity(db, entity_id)
    return EntityPublic.model_validate(entity)


@router.get(
    "/entities/{entity_id}/relationships",
    response_model=EntityRelationshipsResponse,
    tags=["entities"],
)
async def get_entity_relationships(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("entity:read")),
):
    """Get outgoing and incoming relationships for an entity."""
    entity = await service.get_entity(db, entity_id)
    outgoing, incoming = await service.get_entity_relationships(db, entity_id)
    return {
        "outgoing": [EntityRelationshipPublic.model_validate(r) for r in outgoing],
        "incoming": [EntityRelationshipPublic.model_validate(r) for r in incoming],
    }


@router.post("/entities", response_model=EntityPublic, status_code=201, tags=["entities"])
async def create_entity(
    payload: EntityCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:create")),
):
    """Create a new analyst-driven entity."""
    entity = await service.create_entity(db, payload.model_dump(), created_by=actor.id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="entity.create",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="entity",
        resource_id=str(entity.id),
        ip_address=ip,
        user_agent=ua,
        details={
            "name": entity.name,
            "entity_type": entity.entity_type,
            "status": entity.status,
            "confidence": entity.confidence,
        },
    )
    return EntityPublic.model_validate(entity)


@router.patch("/entities/{entity_id}", response_model=EntityPublic, tags=["entities"])
async def update_entity(
    entity_id: uuid.UUID,
    payload: EntityUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:update")),
):
    """Update an entity."""
    entity = await service.get_entity(db, entity_id)
    changes = payload.model_dump(exclude_unset=True)

    # Capture original values before update for audit trail
    before_values = {key: getattr(entity, key) for key in changes.keys()}

    entity = await service.update_entity(db, entity, changes, updated_by=actor.id)
    ip, ua = _client(request)

    # Build audit details with before/after values
    audit_details = {}
    for key, after_value in changes.items():
        before_value = before_values.get(key)
        audit_details[key] = {"before": before_value, "after": after_value}

    await write_audit(
        db,
        action="entity.update",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="entity",
        resource_id=str(entity.id),
        ip_address=ip,
        user_agent=ua,
        details=audit_details,
    )
    return EntityPublic.model_validate(entity)


@router.post(
    "/entities/{entity_id}/archive/{archive_id}",
    response_model=ArchiveEntityPublic,
    status_code=201,
    tags=["entities"],
)
async def link_archive_to_entity(
    entity_id: uuid.UUID,
    archive_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:link:archive")),
):
    """Link an archive item to an entity."""
    link = await service.link_archive_to_entity(db, entity_id, archive_id, linked_by=actor.id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="entity.archive.link",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="archive_entity",
        resource_id=f"{entity_id}:{archive_id}",
        ip_address=ip,
        user_agent=ua,
        details={"entity_id": str(entity_id), "archive_id": str(archive_id)},
    )
    return ArchiveEntityPublic.model_validate(link)


@router.delete(
    "/entities/{entity_id}/archive/{archive_id}", status_code=204, tags=["entities"]
)
async def unlink_archive_from_entity(
    entity_id: uuid.UUID,
    archive_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:link:archive")),
):
    """Unlink an archive item from an entity."""
    link_data = await service.unlink_archive_from_entity(db, entity_id, archive_id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="entity.archive.unlink",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="archive_entity",
        resource_id=f"{entity_id}:{archive_id}",
        ip_address=ip,
        user_agent=ua,
        details=link_data,
    )


@router.post(
    "/entities/{entity_id}/event/{event_id}",
    response_model=EventEntityPublic,
    status_code=201,
    tags=["entities"],
)
async def link_entity_to_event(
    entity_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:link:event")),
):
    """Link an entity to an event."""
    link = await service.link_entity_to_event(db, entity_id, event_id, linked_by=actor.id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="entity.event.link",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="event_entity",
        resource_id=f"{entity_id}:{event_id}",
        ip_address=ip,
        user_agent=ua,
        details={"entity_id": str(entity_id), "event_id": str(event_id)},
    )
    return EventEntityPublic.model_validate(link)


@router.delete(
    "/entities/{entity_id}/event/{event_id}", status_code=204, tags=["entities"]
)
async def unlink_entity_from_event(
    entity_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:link:event")),
):
    """Unlink an entity from an event."""
    await service.unlink_entity_from_event(db, entity_id, event_id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="entity.event.unlink",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="event_entity",
        resource_id=f"{entity_id}:{event_id}",
        ip_address=ip,
        user_agent=ua,
        details={"entity_id": str(entity_id), "event_id": str(event_id)},
    )


@router.post(
    "/entities/{from_id}/relate/{to_id}",
    response_model=EntityRelationshipPublic,
    status_code=201,
    tags=["entities"],
)
async def create_relationship(
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    payload: EntityRelationshipCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:relate")),
):
    """Create a relationship between two entities."""
    rel = await service.create_relationship(
        db,
        from_id,
        to_id,
        payload.relation_type,
        payload.confidence,
        created_by=actor.id,
    )
    ip, ua = _client(request)
    await write_audit(
        db,
        action="relationship.created",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="entity_relationship",
        resource_id=str(rel.id),
        ip_address=ip,
        user_agent=ua,
        details={
            "from_entity_id": str(from_id),
            "to_entity_id": str(to_id),
            "relation_type": payload.relation_type,
            "confidence": payload.confidence,
        },
    )
    return EntityRelationshipPublic.model_validate(rel)


@router.delete("/relationships/{relationship_id}", status_code=204, tags=["entities"])
async def delete_relationship(
    relationship_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("entity:relate")),
):
    """Delete a relationship (hard delete). Audit captures deleted details."""
    rel_data = await service.delete_relationship(db, relationship_id)
    ip, ua = _client(request)
    await write_audit(
        db,
        action="relationship.deleted",
        actor_id=actor.id,
        actor_email=actor.email,
        resource_type="entity_relationship",
        resource_id=str(relationship_id),
        ip_address=ip,
        user_agent=ua,
        details=rel_data,
    )
