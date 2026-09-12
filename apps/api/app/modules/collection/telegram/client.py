"""Telegram client factory + test override.

Returns a configured real client, or None when credentials are absent (so the
collector degrades cleanly to a 'not configured' failure — never fake data).
Tests inject a FakeTelegramClient via set_client_override().
"""
from __future__ import annotations

from app.core.config import get_settings
from app.modules.collection.telegram.port import TelegramClientPort

_override: TelegramClientPort | None = None


def set_client_override(client: TelegramClientPort | None) -> None:
    global _override
    _override = client


def get_telegram_client() -> TelegramClientPort | None:
    if _override is not None:
        return _override
    s = get_settings()
    if not s.telegram_configured:
        return None
    from app.modules.collection.telegram.telethon_adapter import TelethonClient

    return TelethonClient(
        api_id=s.telegram_api_id,
        api_hash=s.telegram_api_hash,
        session_string=s.telegram_session_string,
        flood_threshold=s.telegram_flood_sleep_threshold,
    )
