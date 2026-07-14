"""Конфигурация из окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
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
    tz_name: str = os.getenv("TZ", "Asia/Tashkent")  # Узбекистан (UTC+5, без перехода)
    webapp_url: str = os.getenv("WEBAPP_URL", "").strip()
    # Прямой контакт сотрудника P&C для обратной связи.
    feedback_url: str = os.getenv("FEEDBACK_URL", "https://t.me/DaryaPMI").strip()
    # Старт марафона: до этой даты бот не принимает шаги, а «Прогресс» заблюрен.
    marathon_start: date = date.fromisoformat(os.getenv("MARATHON_START", "2026-07-17"))
    marathon_end: date = date.fromisoformat(os.getenv("MARATHON_END", "2026-08-07"))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def validate(self) -> None:
        if not self.bot_token:
            raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните.")


config = Config()
