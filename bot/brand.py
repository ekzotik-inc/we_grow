"""Фирменное оформление WE GROW: картинка главного меню и аватар бота.

Картинки собраны из иллюстрации слайда «Стартуем!» без надписей
(assets/brand/menu.jpg — 1280×720, avatar.jpg — 640×640, безопасна для круга).

Меню хранится в settings.menu_media в виде {"type": "photo", "asset": путь};
при первом показе файл загружается в Telegram и заменяется на file_id
(bot/menu.py). Аватар ставится методом setMyProfilePhoto.
На старте всё применяется один раз (флаги brand_menu_v1 / brand_avatar_v1);
повторить вручную — «⚙️ Оформление» в админ-панели.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InputProfilePhotoStatic

from bot import settings

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MENU_ASSET = "brand/menu.jpg"
AVATAR = ASSETS / "brand" / "avatar.jpg"


async def use_default_menu() -> None:
    await settings.set("menu_media", json.dumps({"type": "photo", "asset": MENU_ASSET}))


async def set_avatar(bot: Bot) -> bool:
    try:
        await bot.set_my_profile_photo(
            photo=InputProfilePhotoStatic(photo=FSInputFile(AVATAR)))
        return True
    except Exception as e:  # noqa: BLE001 — косметика не должна валить бота
        log.warning("не удалось поставить аватар бота: %s", e)
        return False


# Иконки кнопок главного меню из набора Animated Emoji (icon_custom_emoji_id).
MENU_ICONS = {
    "steps": "5188501157072347830",   # 👣,
    "weekly": "5373001317042101552",   # 📈,
    "progress": "5431577498364158238",   # 📊,
    "board": "5409008750893734809",   # 🏆,
    "rules": "5226512880362332956",   # 📖,
    "help": "5472146462362048818",   # 💡,
    "feedback": "5465300082628763143",   # 💬
}


async def use_default_icons() -> None:
    for name, cid in MENU_ICONS.items():
        await settings.set(f"icon_{name}", cid)


async def apply_once(bot: Bot) -> None:
    """Разово на старте: фирменная картинка меню и аватар."""
    if not settings.get("brand_menu_v1"):
        await use_default_menu()
        await settings.set("brand_menu_v1", "1")
        log.info("Картинка главного меню WE GROW установлена")
    if not settings.get("brand_icons_v2"):
        await use_default_icons()
        await settings.set("brand_icons_v2", "1")
        log.info("Иконки кнопок меню обновлены на набор Animated Emoji")
    if not settings.get("brand_avatar_v1") and await set_avatar(bot):
        await settings.set("brand_avatar_v1", "1")
        log.info("Аватар бота WE GROW установлен")
