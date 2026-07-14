"""Middleware: блокировка дисквалифицированных участников.

Пока у участника проставлен disqualified_at, любые его действия в боте
игнорируются — он получает единственное сообщение о блокировке. Админы
(config.admin_ids) под блокировку не попадают. Снятие дисквалификации из
админ-панели немедленно возвращает доступ.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import db, settings, texts


class BlockDisqualifiedMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or settings.is_admin(user.id):
            return await handler(event, data)

        if await db.is_disqualified(user.id):
            if isinstance(event, Message):
                await event.answer(texts.DISQUALIFIED_BLOCK)
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.DISQUALIFIED_BLOCK_SHORT, show_alert=True)
            return None  # не пускаем дальше — все действия заблокированы

        return await handler(event, data)
