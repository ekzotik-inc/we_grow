"""Настройки, управляемые из админ-панели. Кэш в памяти + хранение в БД.

Ключи:
  menu_media   — JSON {"type": "photo|animation|video", "file_id": "..."}
  menu_caption — подпись под медиа главного меню
  label_<name> — подпись кнопки (steps/progress/board/rules/help)
"""
from __future__ import annotations

import json

_cache: dict[str, str] = {}

DEFAULT_LABELS = {
    "steps": "👟 Шаги за сегодня",
    "progress": "📊 Мой прогресс",
    "board": "🏆 Лидерборд",
    "rules": "📋 Правила",
    "help": "❓ Помощь",
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
