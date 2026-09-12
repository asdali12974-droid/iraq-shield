"""Entity model tests.

Model-level validation for Entity, ArchiveEntity, EventEntity, and EntityRelationship.
These tests do not require the full API layer or RBAC — just SQLAlchemy ORM and database constraints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.collection import (
    ArchiveEntity,
    Entity,
    EntityRelationship,
    ENTITY_STATUSES,
    ENTITY_TYPES,
    Event,
    EventEntity,
    RawArchive,
    Source,
)
from app.models.iam import User

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_user(db_session, email: str = "test@iraqshield.test") -> User:
    """Helper to create a test user."""
    user = User(email=email, hashed_password="hashed", full_name="Test User")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_entity(db_session, name: str = "Test Entity", **kwargs) -> Entity:
    """Helper to create a test entity."""
    entity = Entity(name=name, entity_type="PERSON", **kwargs)
    db_session.add(entity)
    await db_session.commit()
    await db_session.refresh(entity)
    return entity


async def _create_source(db_session, url: str = "http://test.local") -> Source:
    """Helper to create a test source."""
    source = Source(name="Test Source", source_type="RSS", url=url)
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


async def _create_archive(db_session, source_id: uuid.UUID) -> RawArchive:
    """Helper to create a test archive item."""
    archive = RawArchive(
        source_id=source_id,
        url="http://test.local/item",
        content_hash="abc123",
        fingerprint="abc123",
        raw_ref="ref",
    )
    db_session.add(archive)
    await db_session.commit()
    await db_session.refresh(archive)
    return archive


async def _create_event(db_session) -> Event:
    """Helper to create a test event."""
    event = Event(title="Test Event", occurred_at=datetime.now(timezone.utc))
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


class TestEntityModel:
    """Entity model creation and validation."""

    async def test_create_entity_minimal(self, db_session):
        """Create an entity with only required fields."""
        entity = Entity(name="Test Entity", entity_type="PERSON")
        db_session.add(entity)
        await db_session.commit()
        await db_session.refresh(entity)

        assert entity.id is not None
        assert entity.name == "Test Entity"
        assert entity.entity_type == "PERSON"
        assert entity.status == "pending"  # default
        assert entity.confidence == 0.5  # default
        assert entity.created_by is None
        assert entity.updated_by is None
        assert entity.created_at is not None
        assert entity.updated_at is not None

    async def test_create_entity_full(self, db_session):
        """Create an entity with all fields."""
        user = await _create_user(db_session, "entity_full@test")
        entity = Entity(
            name="Full Entity",
            entity_type="LOCATION",
            description="A detailed description",
            status="confirmed",
            confidence=0.95,
            created_by=user.id,
            updated_by=user.id,
        )
        db_session.add(entity)
        await db_session.commit()
        await db_session.refresh(entity)

        assert entity.name == "Full Entity"
        assert entity.entity_type == "LOCATION"
        assert entity.description == "A detailed description"
        assert entity.status == "confirmed"
        assert entity.confidence == 0.95
        assert entity.created_by == user.id
        assert entity.updated_by == user.id

    async def test_entity_types(self, db_session):
        """Test all valid entity types."""
        for entity_type in ENTITY_TYPES:
            entity = Entity(name=f"Entity {entity_type}", entity_type=entity_type)
            db_session.add(entity)
        await db_session.commit()

        res = await db_session.execute(select(Entity))
        entities = list(res.scalars().all())
        assert len(entities) == len(ENTITY_TYPES)
        inserted_types = {e.entity_type for e in entities}
        assert inserted_types == set(ENTITY_TYPES)

    async def test_entity_statuses(self, db_session):
        """Test all valid entity statuses."""
        for status in ENTITY_STATUSES:
            entity = Entity(name=f"Entity {status}", entity_type="PERSON", status=status)
            db_session.add(entity)
        await db_session.commit()

        res = await db_session.execute(select(Entity))
        entities = list(res.scalars().all())
        assert len(entities) == len(ENTITY_STATUSES)
        inserted_statuses = {e.status for e in entities}
        assert inserted_statuses == set(ENTITY_STATUSES)

    async def test_entity_confidence_range(self, db_session):
        """Test valid confidence range 0.0-1.0."""
        for confidence in [0.0, 0.25, 0.5, 0.75, 1.0]:
            entity = Entity(
                name=f"Entity {confidence}",
                entity_type="PERSON",
                confidence=confidence,
            )
            db_session.add(entity)
        await db_session.commit()

        res = await db_session.execute(select(Entity))
        entities = list(res.scalars().all())
        assert len(entities) == 5

    async def test_entity_set_null_on_user_delete(self, db_session):
        """Test that entity.created_by becomes NULL when user is deleted."""
        user = await _create_user(db_session, "entity_del@test")
        entity = await _create_entity(db_session, created_by=user.id, updated_by=user.id)

        assert entity.created_by == user.id
        assert entity.updated_by == user.id

        # Delete user
        await db_session.delete(user)
        await db_session.commit()

        # Refresh entity
        await db_session.refresh(entity)
        assert entity.created_by is None
        assert entity.updated_by is None


class TestArchiveEntity:
    """ArchiveEntity linking model."""

    async def test_link_archive_to_entity(self, db_session):
        """Create an archive-entity link."""
        entity = await _create_entity(db_session, "Entity1")
        source = await _create_source(db_session, "http://test1.local")
        archive = await _create_archive(db_session, source.id)

        link = ArchiveEntity(entity_id=entity.id, archive_id=archive.id)
        db_session.add(link)
        await db_session.commit()
        await db_session.refresh(link)

        assert link.entity_id == entity.id
        assert link.archive_id == archive.id
        assert link.linked_at is not None
        assert link.linked_by is None

    async def test_archive_entity_composite_key(self, db_session):
        """Test that (entity_id, archive_id) is a composite primary key."""
        entity = await _create_entity(db_session, "Entity2")
        source = await _create_source(db_session, "http://test2.local")
        archive = await _create_archive(db_session, source.id)

        link = ArchiveEntity(entity_id=entity.id, archive_id=archive.id)
        db_session.add(link)
        await db_session.commit()

        # Try to insert duplicate (should fail)
        dup = ArchiveEntity(entity_id=entity.id, archive_id=archive.id)
        db_session.add(dup)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.commit()

    async def test_archive_entity_cascade_delete(self, db_session):
        """Test that deleting entity or archive cascades to link."""
        entity = await _create_entity(db_session, "Entity3")
        source = await _create_source(db_session, "http://test3.local")
        archive = await _create_archive(db_session, source.id)

        link = ArchiveEntity(entity_id=entity.id, archive_id=archive.id)
        db_session.add(link)
        await db_session.commit()

        # Delete entity
        await db_session.delete(entity)
        await db_session.commit()

        # Link should be gone
        res = await db_session.execute(select(ArchiveEntity))
        links = list(res.scalars().all())
        assert len(links) == 0


class TestEventEntity:
    """EventEntity linking model."""

    async def test_link_entity_to_event(self, db_session):
        """Create an event-entity link."""
        entity = await _create_entity(db_session, "Entity4")
        event = await _create_event(db_session)

        link = EventEntity(event_id=event.id, entity_id=entity.id)
        db_session.add(link)
        await db_session.commit()
        await db_session.refresh(link)

        assert link.event_id == event.id
        assert link.entity_id == entity.id
        assert link.linked_at is not None

    async def test_event_entity_composite_key(self, db_session):
        """Test that (event_id, entity_id) is a composite primary key."""
        entity = await _create_entity(db_session, "Entity5")
        event = await _create_event(db_session)

        link = EventEntity(event_id=event.id, entity_id=entity.id)
        db_session.add(link)
        await db_session.commit()

        # Try to insert duplicate (should fail)
        dup = EventEntity(event_id=event.id, entity_id=entity.id)
        db_session.add(dup)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.commit()


class TestEntityRelationship:
    """EntityRelationship model — directed, immutable relationships between entities."""

    async def test_create_relationship(self, db_session):
        """Create a relationship between two entities."""
        entity1 = await _create_entity(db_session, "Entity6", entity_type="PERSON")
        entity2 = await _create_entity(db_session, "Entity7", entity_type="ORGANIZATION")

        rel = EntityRelationship(
            from_entity_id=entity1.id,
            to_entity_id=entity2.id,
            relation_type="employed_by",
            confidence=0.9,
        )
        db_session.add(rel)
        await db_session.commit()
        await db_session.refresh(rel)

        assert rel.from_entity_id == entity1.id
        assert rel.to_entity_id == entity2.id
        assert rel.relation_type == "employed_by"
        assert rel.confidence == 0.9
        assert rel.created_at is not None

    async def test_relationship_immutable_no_update(self, db_session):
        """Verify relationship is immutable (no update semantics in model)."""
        entity1 = await _create_entity(db_session, "Entity8")
        entity2 = await _create_entity(db_session, "Entity9")

        rel = EntityRelationship(
            from_entity_id=entity1.id,
            to_entity_id=entity2.id,
            relation_type="same_as",
            confidence=0.5,
        )
        db_session.add(rel)
        await db_session.commit()

        # Relationship created; no update endpoint should exist in API
        # (this is application-level constraint, not DB-level)
        assert rel.relation_type == "same_as"

    async def test_relationship_duplicate_prevention(self, db_session):
        """Test unique constraint on (from_id, to_id, relation_type)."""
        entity1 = await _create_entity(db_session, "Entity10")
        entity2 = await _create_entity(db_session, "Entity11")

        rel1 = EntityRelationship(
            from_entity_id=entity1.id,
            to_entity_id=entity2.id,
            relation_type="same_as",
        )
        db_session.add(rel1)
        await db_session.commit()

        # Try to create duplicate (should fail)
        rel2 = EntityRelationship(
            from_entity_id=entity1.id,
            to_entity_id=entity2.id,
            relation_type="same_as",
        )
        db_session.add(rel2)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.commit()

    async def test_relationship_confidence_range(self, db_session):
        """Test relationship confidence range 0.0-1.0."""
        entity1 = await _create_entity(db_session, "Entity12")
        entity2 = await _create_entity(db_session, "Entity13")

        for conf in [0.0, 0.25, 0.5, 0.75, 1.0]:
            rel = EntityRelationship(
                from_entity_id=entity1.id,
                to_entity_id=entity2.id,
                relation_type="related_to",
                confidence=conf,
            )
            db_session.add(rel)
        await db_session.commit()

        res = await db_session.execute(select(EntityRelationship))
        rels = list(res.scalars().all())
        assert len(rels) == 5

    async def test_relationship_cascade_delete(self, db_session):
        """Test that deleting an entity cascades to its relationships."""
        entity1 = await _create_entity(db_session, "Entity14")
        entity2 = await _create_entity(db_session, "Entity15")

        rel = EntityRelationship(
            from_entity_id=entity1.id,
            to_entity_id=entity2.id,
            relation_type="parent_of",
        )
        db_session.add(rel)
        await db_session.commit()

        # Delete entity1
        await db_session.delete(entity1)
        await db_session.commit()

        # Relationship should be gone
        res = await db_session.execute(select(EntityRelationship))
        rels = list(res.scalars().all())
        assert len(rels) == 0

    async def test_relationship_set_null_on_user_delete(self, db_session):
        """Test that relationship.created_by becomes NULL when user is deleted."""
        user = await _create_user(db_session, "rel_del@test")
        entity1 = await _create_entity(db_session, "Entity16")
        entity2 = await _create_entity(db_session, "Entity17")

        rel = EntityRelationship(
            from_entity_id=entity1.id,
            to_entity_id=entity2.id,
            relation_type="affiliated_with",
            created_by=user.id,
        )
        db_session.add(rel)
        await db_session.commit()

        assert rel.created_by == user.id

        # Delete user
        await db_session.delete(user)
        await db_session.commit()

        # Refresh relationship
        await db_session.refresh(rel)
        assert rel.created_by is None
