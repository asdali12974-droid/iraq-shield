"""Register the platform-manager's initial Telegram source list.

This seeds SOURCE CONFIGURATION provided by the admin (channel usernames +
editorial classification) — it is NOT content and NOT fabricated posts. Every
source is created:
  - DISABLED (the scheduler will not collect it),
  - verification_status = 'pending' (usernames are NOT verified here; a real
    resolve must run against Telegram before any collection),
  - reliability = 'C' as a neutral default that an analyst can change.

Idempotent: re-running skips channels that already exist (by URL).

Run:  python -m scripts.seed_telegram_sources
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_sessionmaker
from app.models.collection import Source

log = get_logger("seed_telegram")

# (username, display_name, source_class)
SOURCES: list[tuple[str, str, str]] = [
    # OFFICIAL
    ("inainaiq", "وكالة الأنباء العراقية «واع»", "OFFICIAL"),
    ("IraqiMediaNetwork", "شبكة الإعلام العراقي", "OFFICIAL"),
    ("moiiraqi", "وزارة الداخلية العراقية", "OFFICIAL"),
    ("ModIraq", "وزارة الدفاع العراقية", "OFFICIAL"),
    ("parliament_iq", "مجلس النواب العراقي", "OFFICIAL"),
    ("iraqicts", "جهاز مكافحة الإرهاب", "OFFICIAL"),
    ("alhashed_alshaebe", "هيئة الحشد الشعبي", "OFFICIAL"),
    ("teamsmediawar_1", "مديرية إعلام الحشد الشعبي", "OFFICIAL"),
    # POLITICAL / MEDIA
    ("jawabna", "المكتب الخاص للسيد مقتدى الصدر", "POLITICAL_MEDIA"),
    ("alahadtvofficial", "قناة العهد", "POLITICAL_MEDIA"),
    # OTHER / MEDIA
    ("Alomhoar", "Alomhoar", "MEDIA_OTHER"),
    ("nayaforiraq", "nayaforiraq", "MEDIA_OTHER"),
    ("SabrenNewss", "SabrenNewss", "MEDIA_OTHER"),
    ("Al_3sforh", "Al_3sforh", "MEDIA_OTHER"),
    ("online_alhashd", "online_alhashd", "MEDIA_OTHER"),
    ("Aletejahchanal", "Aletejahchanal", "MEDIA_OTHER"),
    ("iraqforce11", "iraqforce11", "MEDIA_OTHER"),
]


async def run() -> None:
    async with get_sessionmaker()() as db:
        existing = {
            u for (u,) in (await db.execute(select(Source.url))).all()
        }
        created = skipped = 0
        for username, name, klass in SOURCES:
            url = f"https://t.me/{username}"
            if url in existing:
                skipped += 1
                continue
            db.add(
                Source(
                    name=name,
                    source_type="TELEGRAM_PUBLIC",
                    url=url,
                    telegram_username=username,
                    language="ar",
                    country_region="Iraq",
                    source_class=klass,
                    reliability="C",  # neutral default; analyst-editable
                    enabled=False,  # do NOT collect until verified + approved
                    verification_status="pending",
                    collection_interval_seconds=900,
                )
            )
            created += 1
        await db.commit()
        log.info("telegram_seed_done", created=created, skipped=skipped)


async def _main() -> None:
    try:
        await run()
    finally:
        await dispose_engine()


def main() -> None:
    configure_logging(level="INFO", json_output=False)
    asyncio.run(_main())


if __name__ == "__main__":
    main()
