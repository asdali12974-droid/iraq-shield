"""Telegram client port (interface) + value types.

The collector depends only on this narrow port, never on Telethon directly.
Two adapters implement it: `TelethonClient` (real MTProto) and
`FakeTelegramClient` (tests). This is what lets us exercise the full collection
logic without a real Telegram connection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


class TelegramError(Exception):
    """Generic Telegram access error (resolve/connect/read failure)."""


class TelegramNotConfigured(TelegramError):
    """Raised when Telegram credentials are absent."""


class FloodWait(TelegramError):
    """Telegram asked us to wait `seconds` before retrying (rate limit)."""

    def __init__(self, seconds: int):
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds


class ChannelNotPublic(TelegramError):
    """The resolved entity is not a public channel."""


@dataclass
class TgChannel:
    channel_id: int
    username: str
    title: str
    is_public: bool = True


@dataclass
class TgMessage:
    message_id: int
    date: datetime
    text: str
    edit_date: datetime | None = None
    views: int | None = None
    # Public forward provenance, if any.
    fwd_from_username: str | None = None
    fwd_from_channel_id: int | None = None
    fwd_from_message_id: int | None = None
    # Media METADATA only (no file download): {"type","mime","size",...}.
    media_meta: dict | None = None
    raw: dict = field(default_factory=dict)


@runtime_checkable
class TelegramClientPort(Protocol):
    async def connect(self) -> None: ...

    async def resolve_channel(self, username: str) -> TgChannel: ...

    async def fetch_messages(
        self, channel: TgChannel, *, min_id: int = 0, limit: int = 200
    ) -> list[TgMessage]:
        """Return public messages with id > min_id, oldest-first, capped at limit."""
        ...

    async def disconnect(self) -> None: ...
