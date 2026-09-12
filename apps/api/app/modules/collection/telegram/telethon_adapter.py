"""Real MTProto adapter (Telethon). Reads PUBLIC channels only.

Telethon is imported lazily so the rest of the app never depends on it. Secrets
(api_id/api_hash/session) are held in memory only and never logged.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.modules.collection.telegram.port import (
    ChannelNotPublic,
    FloodWait,
    TelegramError,
    TgChannel,
    TgMessage,
)

log = get_logger("telegram")


class TelethonClient:
    def __init__(self, api_id: int, api_hash: str, session_string: str, flood_threshold: int = 60):
        # Held in memory only; never logged.
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_string = session_string
        self._flood_threshold = flood_threshold
        self._client = None
        self._entities: dict[str, object] = {}

    async def connect(self) -> None:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise TelegramError("telethon is not installed") from exc

        self._client = TelegramClient(
            StringSession(self._session_string), self._api_id, self._api_hash
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise TelegramError("Telegram session is not authorized")
        log.info("telegram_connected")  # no secrets

    async def resolve_channel(self, username: str) -> TgChannel:
        from telethon.errors import FloodWaitError
        from telethon.tl.types import Channel

        try:
            entity = await self._client.get_entity(username)
        except FloodWaitError as exc:
            raise FloodWait(int(exc.seconds)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ChannelNotPublic(f"cannot resolve {username}") from exc

        if not isinstance(entity, Channel) or not getattr(entity, "broadcast", False):
            raise ChannelNotPublic(f"{username} is not a broadcast channel")
        uname = getattr(entity, "username", None)
        if not uname:
            raise ChannelNotPublic(f"{username} is not public")
        self._entities[uname.lower()] = entity
        return TgChannel(
            channel_id=int(entity.id),
            username=uname,
            title=getattr(entity, "title", uname) or uname,
            is_public=True,
        )

    async def fetch_messages(
        self, channel: TgChannel, *, min_id: int = 0, limit: int = 200
    ) -> list[TgMessage]:
        from telethon.errors import FloodWaitError

        entity = self._entities.get(channel.username.lower())
        if entity is None:
            entity = (await self.resolve_channel(channel.username)) and self._entities.get(
                channel.username.lower()
            )
        out: list[TgMessage] = []
        try:
            async for m in self._client.iter_messages(
                entity, min_id=min_id, limit=limit, reverse=True
            ):
                out.append(self._map(m))
        except FloodWaitError as exc:
            raise FloodWait(int(exc.seconds)) from exc
        return out

    def _map(self, m) -> TgMessage:
        fwd_username = fwd_cid = fwd_mid = None
        fwd = getattr(m, "fwd_from", None)
        if fwd is not None:
            fwd_mid = getattr(fwd, "channel_post", None)
            from_id = getattr(fwd, "from_id", None)
            cid = getattr(from_id, "channel_id", None)
            if cid is not None:
                fwd_cid = int(cid)

        media_meta = None
        media = getattr(m, "media", None)
        if media is not None:
            media_meta = {"type": type(media).__name__}

        def _dt(v):
            if v is None:
                return None
            return v if v.tzinfo else v.replace(tzinfo=UTC)

        return TgMessage(
            message_id=int(m.id),
            date=_dt(m.date) or datetime.now(tz=UTC),
            text=m.message or "",
            edit_date=_dt(getattr(m, "edit_date", None)),
            views=getattr(m, "views", None),
            fwd_from_username=fwd_username,
            fwd_from_channel_id=fwd_cid,
            fwd_from_message_id=fwd_mid,
            media_meta=media_meta,
            raw={"id": int(m.id)},
        )

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
