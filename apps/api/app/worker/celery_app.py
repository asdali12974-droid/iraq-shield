"""Celery application (worker + beat scheduler).

Broker & result backend are Redis (the same instance the app already uses). The
beat schedule periodically scans for due sources and dispatches collection.
Run:
    worker:    celery -A app.worker.celery_app.celery worker -l info
    scheduler: celery -A app.worker.celery_app.celery beat -l info
"""
from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_s = get_settings()


def _redis_url(db: int) -> str:
    auth = f":{_s.redis_password}@" if _s.redis_password else ""
    return f"redis://{auth}{_s.redis_host}:{_s.redis_port}/{db}"


celery = Celery(
    "iraqshield",
    broker=_redis_url(_s.redis_db + 1),
    backend=_redis_url(_s.redis_db + 2),
    include=["app.worker.tasks"],
)

celery.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=240,
    timezone="UTC",
    beat_schedule={
        "collect-due-sources": {
            "task": "app.worker.tasks.collect_due_sources",
            # Scan every minute; each source's own interval gates real collection.
            "schedule": 60.0,
        }
    },
)
