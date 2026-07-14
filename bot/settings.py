"""Настройки, управляемые из админ-панели. Кэш в памяти + хранение в БД.

Ключи:
  menu_media    — JSON {"type": "photo|animation|video", "file_id": "..."}
  menu_caption  — подпись под медиа главного меню
  label_<name>  — подпись кнопки (steps/progress/board/rules/help)
  webapp_url    — URL Mini App (переопределяет env, чтобы менять без редеплоя)
  channel_join  — chat_id канала для заявок на вступление
  channel_review— chat_id канала для проверки результатов
"""
from __future__ import annotations

import json

from bot.config import config

_cache: dict[str, str] = {}

DEFAULT_LABELS = {
    "steps": "👟 Шаги за сегодня",
    "progress": "📊 Мой прогресс",
    "board": "🏆 Лидерборд",
    "rules": "📋 Правила",
    "help": "❓ Помощь",
    "feedback": "💬 Обратная связь",
}


async def load() -> None:
    from bot import db
    _cache.clear()
    _cache.update(await db.all_settings())


async def set(key: str, value: str | None) -> None:  # noqa: A003
    from bot import db
    await db.set_setting(key, value)
    if value is None:
        _cache.pop(key, None)
    else:
        _cache[key] = value


def get(key: str, default: str | None = None) -> str | None:
    return _cache.get(key, default)


def label(name: str) -> str:
    return _cache.get(f"label_{name}") or DEFAULT_LABELS[name]


def icon(name: str) -> str | None:
    """custom_emoji_id иконки кнопки (Bot API 9.4). None — без иконки."""
    return _cache.get(f"icon_{name}")


def all_labels() -> dict[str, str]:
    return {name: label(name) for name in DEFAULT_LABELS}


def menu_media() -> dict | None:
    raw = _cache.get("menu_media")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def set_menu_media(kind: str, file_id: str) -> None:
    await set("menu_media", json.dumps({"type": kind, "file_id": file_id}))


def webapp_url() -> str:
    """URL Mini App: сначала настройка из админки, затем env. Позволяет
    включить кнопки «Прогресс/Лидерборд» без редеплоя (частая причина
    ошибки «открой приложение из бота» — незаданный WEBAPP_URL)."""
    return _cache.get("webapp_url") or config.webapp_url


def channel_id(kind: str) -> int | None:
    """chat_id канала для заявок (kind='join') или проверки (kind='review')."""
    raw = _cache.get(f"channel_{kind}")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None
