"""Какой экземпляр бота отвечает и не запущен ли второй.

Render передаёт в окружение имя сервиса и коммит (RENDER_SERVICE_NAME,
RENDER_GIT_COMMIT). Если тот же токен опрашивает ещё один процесс (старый
сервис в Render, локальный запуск), Telegram отвечает на getUpdates
ошибкой Conflict — ConflictWatch ловит её и раз в час пишет админам.
"""
from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramConflictError

log = logging.getLogger(__name__)

STARTED = datetime.now()
_ALERT_EVERY = 3600
_last_alert = 0.0


def describe() -> str:
    service = os.getenv("RENDER_SERVICE_NAME") or socket.gethostname()
    commit = (os.getenv("RENDER_GIT_COMMIT") or "")[:7] or "—"
    return f"{service} · коммит {commit} · запущен {STARTED.strftime('%d.%m %H:%M')}"


class ConflictWatch(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        global _last_alert
        try:
            return await make_request(bot, method)
        except TelegramConflictError:
            if type(method).__name__ == "GetUpdates" and time.time() - _last_alert > _ALERT_EVERY:
                _last_alert = time.time()
                log.error("КОНФЛИКТ: бот запущен где-то ещё (%s)", describe())
                from bot import settings
                text = ("⚠️ <b>Запущен второй экземпляр бота</b>\n\n"
                        "Telegram сообщает, что этого бота одновременно опрашивает "
                        "другой процесс с тем же токеном. Пока их два, бот отвечает "
                        "через раз и может показывать старые кнопки.\n\n"
                        "Остановите лишний сервис в Render (Suspend), оставьте один.\n"
                        f"Это сообщение отправил: <code>{describe()}</code>")
                for admin_id in sorted(settings.admin_ids()):
                    try:
                        await bot.send_message(admin_id, text)
                    except Exception:  # noqa: BLE001
                        pass
            raise
