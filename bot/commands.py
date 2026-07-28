"""Меню команд («/») — общий список и применение к конкретному чату.

Живёт отдельным модулем, чтобы обновлять меню не только на старте бота
(bot/main.py), но и сразу после /addadmin, /deladmin и /start: доп-админы
добавляются на ходу, и их персональный scope нужно ставить в тот же момент.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot import settings

log = logging.getLogger(__name__)

# Участникам показываем только базовые команды — остальное скрыто и доступно
# лишь админам через отдельный scope.
USER_COMMANDS = [
    ("start", "Регистрация / главное меню"),
    ("help", "Как участвовать"),
    ("rules", "Правила марафона"),
]
ADMIN_EXTRA = [
    ("admin", "Админ-панель P&C"),
    ("leaderboard", "Лидерборд"),
    ("stats", "Вовлечённость за день"),
    ("broadcast", "Рассылка участникам"),
    ("instruction", "Рассылка инструкции по скриншотам"),
    ("inactive", "Предупреждение о неактивности"),
    ("scheduled", "Отложенные рассылки"),
    ("export", "Выгрузка в Excel"),
    ("move", "Перевести участника в команду"),
    ("dq", "Дисквалификация: /dq ID"),
    ("delete", "Удалить данные участника: /delete ID"),
    ("addadmin", "Назначить админа: /addadmin ID"),
    ("deladmin", "Снять админа: /deladmin ID"),
    ("emojiid", "Получить emoji-id"),
    ("feedback", "Связь с P&C"),
    ("reset", "Сбросить регистрацию"),
    ("app", "Открыть Mini App (web_app-кнопка)"),
]


def _cmds(pairs) -> list[BotCommand]:
    return [BotCommand(command=c, description=d) for c, d in pairs]


async def apply_for(bot: Bot, tg_id: int) -> bool:
    """Ставит персональное меню команд по текущей роли пользователя.

    Админу (из env или добавленному через /addadmin) — расширенный список,
    остальным — базовый. Возвращает False, если Telegram не принял вызов
    (например, пользователь ещё не начинал диалог с ботом)."""
    pairs = USER_COMMANDS + ADMIN_EXTRA if settings.is_admin(tg_id) else USER_COMMANDS
    try:
        await bot.set_my_commands(_cmds(pairs), scope=BotCommandScopeChat(chat_id=tg_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("commands for %s: %s", tg_id, e)
        return False


async def setup_all(bot: Bot) -> None:
    """Стартовая настройка: общий scope + персональный каждому админу."""
    await bot.set_my_commands(_cmds(USER_COMMANDS), scope=BotCommandScopeDefault())
    for admin_id in sorted(settings.admin_ids()):
        await apply_for(bot, admin_id)
