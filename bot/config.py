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
    # Таймзона марафона — отдельная переменная MARATHON_TZ, по умолчанию
    # Кыргызстан (UTC+6). Системную TZ больше не читаем: в Render у сервисов
    # осталась TZ=Asia/Tashkent от прошлого марафона, и она тихо сдвигала
    # дедлайны, напоминания и картинки дня на час.
    tz_name: str = os.getenv("MARATHON_TZ", "").strip() or "Asia/Bishkek"
    webapp_url: str = os.getenv("WEBAPP_URL", "").strip()
    # Прямой контакт сотрудника P&C для обратной связи.
    feedback_url: str = os.getenv("FEEDBACK_URL", "https://t.me/aidanazhanyshbekova").strip()
    # Старт марафона: до этой даты бот не принимает шаги, а «Прогресс» заблюрен.
    marathon_start: date = date.fromisoformat(os.getenv("MARATHON_START", "2026-10-12"))
    marathon_end: date = date.fromisoformat(os.getenv("MARATHON_END", "2026-11-01"))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def validate(self) -> None:
        if not self.bot_token:
            raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните.")


config = Config()
