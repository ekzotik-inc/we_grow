"""Рассылки: очередь с задержкой под лимит ~30 msg/s Telegram."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from bot import db
from bot.config import config

log = logging.getLogger(__name__)

_BATCH = 25          # держим < 30 msg/s
_PAUSE = 1.0         # секунда между батчами


async def _send(bot: Bot, chat_id: int, text: str, **kw) -> bool:
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await _send(bot, chat_id, text, **kw)
    except Exception as e:  # пользователь заблокировал бота и т.п.
        log.warning("send to %s failed: %s", chat_id, e)
        return False


async def broadcast(bot: Bot, ids: list[int], text: str, **kw) -> int:
    """Массовая рассылка через очередь. Возвращает число доставленных."""
    sent = 0
    for i in range(0, len(ids), _BATCH):
        chunk = ids[i:i + _BATCH]
        results = await asyncio.gather(*(_send(bot, cid, text, **kw) for cid in chunk))
        sent += sum(results)
        if i + _BATCH < len(ids):
            await asyncio.sleep(_PAUSE)
    return sent


async def _send_rich(bot: Bot, chat_id: int, text: str, media: dict | None, markup) -> bool:
    """Отправка сообщения с опциональным медиа (фото/гиф/видео) и кнопками."""
    try:
        if media:
            kind, file_id = media.get("type"), media.get("file_id")
            if kind == "photo":
                await bot.send_photo(chat_id, file_id, caption=text or None, reply_markup=markup)
            elif kind == "animation":
                await bot.send_animation(chat_id, file_id, caption=text or None, reply_markup=markup)
            elif kind == "video":
                await bot.send_video(chat_id, file_id, caption=text or None, reply_markup=markup)
            else:
                await bot.send_message(chat_id, text, reply_markup=markup)
        else:
            await bot.send_message(chat_id, text, reply_markup=markup)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await _send_rich(bot, chat_id, text, media, markup)
    except Exception as e:  # noqa: BLE001
        log.warning("rich send to %s failed: %s", chat_id, e)
        return False


async def broadcast_rich(bot: Bot, ids: list[int], text: str, media: dict | None, markup) -> int:
    sent = 0
    for i in range(0, len(ids), _BATCH):
        chunk = ids[i:i + _BATCH]
        results = await asyncio.gather(*(_send_rich(bot, cid, text, media, markup) for cid in chunk))
        sent += sum(results)
        if i + _BATCH < len(ids):
            await asyncio.sleep(_PAUSE)
    return sent


async def notify_admins(bot: Bot, text: str, **kw) -> None:
    for admin_id in config.admin_ids:
        await _send(bot, admin_id, text, **kw)


async def broadcast_all(bot: Bot, text: str, **kw) -> int:
    return await broadcast(bot, await db.all_active_ids(), text, **kw)
