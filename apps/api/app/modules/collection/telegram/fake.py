"""In-memory fake Telegram client for tests.

Simulates ONLY the protocol boundary the collector uses (connect / resolve /
fetch / disconnect). It never touches the network. Real Telegram connectivity is
therefore NOT exercised by tests that use this fake — see docs/SECURITY notes.
"""
from __future__ import annotations

from app.modules.collection.telegram.port import (
    ChannelNotPublic,
    FloodWait,
    TelegramError,
    TgChannel,
    TgMessage,
)


class FakeTelegramClient:
    def __init__(
        self,
        channels: dict[str, TgChannel] | None = None,
        messages: dict[str, list[TgMessage]] | None = None,
        *,
        flood_once: bool = False,
        connect_fail_times: int = 0,
    ):
        self._channels = channels or {}
        self._messages = messages or {}
        self._flood_once = flood_once
        self._connect_fail_times = connect_fail_times
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.connected = False

    async def connect(self) -> None:
        self.connect_calls += 1
        if self._connect_fail_times > 0:
            self._connect_fail_times -= 1
            raise TelegramError("simulated connect failure")
        self.connected = True

    async def resolve_channel(self, username: str) -> TgChannel:
        key = username.lstrip("@").lower()
        for uname, ch in self._channels.items():
            if uname.lstrip("@").lower() == key:
                if not ch.is_public:
                    raise ChannelNotPublic(f"{username} is not public")
                return ch
        raise ChannelNotPublic(f"cannot resolve {username}")

    async def fetch_messages(
        self, channel: TgChannel, *, min_id: int = 0, limit: int = 200
    ) -> list[TgMessage]:
        if self._flood_once:
            self._flood_once = False
            raise FloodWait(1)
        msgs = self._messages.get(channel.username.lstrip("@"), [])
        newer = [m for m in msgs if m.message_id > min_id]
        newer.sort(key=lambda m: m.message_id)
        return newer[:limit]

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False
