"""Verify the append-only guarantee is enforced by the database itself,
independent of any application-layer discipline."""
from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio(loop_scope="session")

_INSERT = text(
    "INSERT INTO audit_log (id, action, outcome, details) "
    "VALUES (gen_random_uuid(), :action, 'success', '{}'::jsonb)"
)


async def test_insert_is_allowed(db_session):
    await db_session.execute(_INSERT, {"action": "test.append_ok"})
    await db_session.commit()
    count = await db_session.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = 'test.append_ok'")
    )
    assert count >= 1


async def test_update_is_blocked(db_session):
    await db_session.execute(_INSERT, {"action": "test.update_probe"})
    await db_session.commit()
    with pytest.raises(Exception) as exc:
        await db_session.execute(
            text("UPDATE audit_log SET outcome='x' WHERE action='test.update_probe'")
        )
        await db_session.commit()
    assert "append-only" in str(exc.value).lower()
    await db_session.rollback()


async def test_delete_is_blocked(db_session):
    await db_session.execute(_INSERT, {"action": "test.delete_probe"})
    await db_session.commit()
    with pytest.raises(Exception) as exc:
        await db_session.execute(
            text("DELETE FROM audit_log WHERE action='test.delete_probe'")
        )
        await db_session.commit()
    assert "append-only" in str(exc.value).lower()
    await db_session.rollback()
