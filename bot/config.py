"""Конфигурация из окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "").strip()
    return {int(x) for x in raw.split(",") if x.strip()}


@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "postgresql://wegrow:wegrow@localhost:5432/wegrow")
    admin_ids: frozenset[int] = field(default_factory=lambda: frozenset(_admin_ids()))
    tz_name: str = os.getenv("TZ", "Europe/Moscow")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def validate(self) -> None:
        if not self.bot_token:
            raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните.")


config = Config()
