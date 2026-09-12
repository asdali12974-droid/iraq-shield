"""Collector framework.

A collector turns a Source into a list of CollectedItem. New source types are
added by writing a Collector subclass and registering it — the runner, registry,
archive, and API stay unchanged.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.models.collection import Source


@dataclass
class CollectedItem:
    external_id: str  # stable per-source id (guid/link) — the logical-item key
    url: str
    canonical_url: str | None
    title: str | None
    published_at: datetime | None
    language: str | None
    content_type: str
    raw_bytes: bytes  # exactly what is archived
    text_for_fingerprint: str  # normalized-change detection input
    author: str | None = None
    extracted: dict | None = None  # structured article view (WEBSITE)


@dataclass
class CollectResult:
    items: list[CollectedItem] = field(default_factory=list)
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    ip: str | None = None
    discovered: int = 0  # candidate links found (index mode)
    failed: int = 0  # per-item extraction/fetch failures within the run
    cancelled: bool = False


# A cancel check is a zero-arg callable returning True if the run should stop.
CancelCheck = Callable[[], Awaitable[bool]] | Callable[[], bool] | None


class Collector(ABC):
    source_type: str

    @abstractmethod
    async def collect(self, source: Source, should_cancel: CancelCheck = None) -> CollectResult:
        ...


_REGISTRY: dict[str, Collector] = {}


def register(collector: Collector) -> None:
    _REGISTRY[collector.source_type] = collector


def get_collector(source_type: str) -> Collector | None:
    return _REGISTRY.get(source_type)


def registered_types() -> list[str]:
    return sorted(_REGISTRY)
