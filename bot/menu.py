"""Показ главного меню: опциональное медиа (фото/гиф/видео) + reply-клавиатура."""
from __future__ import annotations

from aiogram import Bot

from bot import keyboards, settings


async def send_main_menu(bot: Bot, chat_id: int, greeting: str) -> None:
    media = settings.menu_media()
    kb = keyboards.main_kb()
    if media and media.get("asset") and not media.get("file_id"):
        # Фирменная картинка из assets: грузим файлом один раз, дальше — file_id.
        from aiogram.types import FSInputFile
        from bot.brand import ASSETS
        try:
            msg = await bot.send_photo(chat_id, FSInputFile(ASSETS / media["asset"]),
                                       caption=greeting, reply_markup=kb)
            if getattr(msg, "photo", None):
                await settings.set_menu_media("photo", msg.photo[-1].file_id)
            return
        except Exception:  # noqa: BLE001
            media = None
    if media:
        kind, file_id = media.get("type"), media.get("file_id")
        try:
            if kind == "photo":
                await bot.send_photo(chat_id, file_id, caption=greeting, reply_markup=kb)
                return
            if kind == "animation":
                await bot.send_animation(chat_id, file_id, caption=greeting, reply_markup=kb)
                return
            if kind == "video":
                await bot.send_video(chat_id, file_id, caption=greeting, reply_markup=kb)
                return
        except Exception:  # noqa: BLE001 — если file_id протух, отправим текстом
            pass
    await bot.send_message(chat_id, greeting, reply_markup=kb)
