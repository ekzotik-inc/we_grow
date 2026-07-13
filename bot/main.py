"""Точка входа бота. Запуск: python -m bot.main"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot import db
from bot.config import config
from bot.handlers import admin, onboarding, steps
from bot.scheduler import setup_scheduler

# Списки команд (меню «/»). Разные для участников и админов через scopes.
USER_COMMANDS = [
    ("start", "Регистрация / главное меню"),
    ("rules", "Правила марафона"),
    ("help", "Как участвовать"),
    ("reset", "Сбросить регистрацию"),
]
ADMIN_EXTRA = [
    ("admin", "Админ-панель P&C"),
    ("leaderboard", "Лидерборд"),
    ("stats", "Вовлечённость за день"),
    ("broadcast", "Рассылка участникам"),
    ("dq", "Дисквалификация: /dq ID"),
    ("emojiid", "Получить emoji-id"),
]


async def _setup_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

    def cmds(pairs):
        return [BotCommand(command=c, description=d) for c, d in pairs]

    await bot.set_my_commands(cmds(USER_COMMANDS), scope=BotCommandScopeDefault())
    for admin_id in config.admin_ids:
        try:
            await bot.set_my_commands(cmds(USER_COMMANDS + ADMIN_EXTRA),
                                      scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:  # noqa: BLE001 — админ мог не нажимать /start
            log.warning("commands for admin %s: %s", admin_id, e)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wegrow")


async def main() -> None:
    config.validate()
    await db.connect(config.database_url)
    log.info("БД подключена, схема применена")

    # HTML по умолчанию — нужно для премиум-эмодзи (<tg-emoji>) и <b>.
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    # Порядок важен: admin-команды и онбординг раньше общего приёма шагов.
    dp.include_router(admin.router)
    dp.include_router(onboarding.router)
    dp.include_router(steps.router)

    # Постоянная кнопка меню открывает Mini App (если задан WEBAPP_URL).
    if config.webapp_url:
        from aiogram.types import MenuButtonWebApp, WebAppInfo
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=config.webapp_url))
        )
        log.info("Кнопка меню Mini App: %s", config.webapp_url)

    await _setup_commands(bot)
    log.info("Команды меню настроены")

    scheduler = setup_scheduler(bot)
    scheduler.start()
    log.info("Планировщик запущен")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Старт polling")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            raise
        log.info("Остановлено")
