"""Какой экземпляр бота отвечает и не запущен ли второй.

Render передаёт в окружение имя сервиса и коммит (RENDER_SERVICE_NAME,
RENDER_GIT_COMMIT). Если тот же токен опрашивает ещё один процесс (старый
сервис в Render, локальный запуск), Telegram отвечает на getUpdates
ошибкой Conflict — ConflictWatch ловит её и раз в час пишет админам, но
только если конфликт устойчивый (не перекрытие версий при деплое).
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
_STARTED_TS = time.time()
_ALERT_EVERY = 3600
# При деплое Render сначала поднимает новую версию и только потом гасит
# старую — пару минут работают обе, и Telegram отвечает Conflict. Это не
# повод для тревоги: пишем админам, только если конфликт не связан со
# стартом (первые 5 минут игнорируем) и держится непрерывно дольше 2 минут.
_GRACE_AFTER_START = 300
_PERSIST = 120
_RESET_GAP = 90
_last_alert = float("-inf")
_first_conflict = 0.0
_last_conflict = 0.0


def describe() -> str:
    service = os.getenv("RENDER_SERVICE_NAME") or socket.gethostname()
    commit = (os.getenv("RENDER_GIT_COMMIT") or "")[:7] or "—"
    return f"{service} · коммит {commit} · запущен {STARTED.strftime('%d.%m %H:%M')}"


class ConflictWatch(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        global _last_alert, _first_conflict, _last_conflict
        try:
            return await make_request(bot, method)
        except TelegramConflictError:
            now = time.time()
            if type(method).__name__ != "GetUpdates":
                raise
            if now - _last_conflict > _RESET_GAP:      # новая серия конфликтов
                _first_conflict = now
            _last_conflict = now
            persistent = (now - _STARTED_TS > _GRACE_AFTER_START
                          and now - _first_conflict >= _PERSIST)
            if persistent and now - _last_alert > _ALERT_EVERY:
                _last_alert = now
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
