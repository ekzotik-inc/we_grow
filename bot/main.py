"""Точка входа бота. Запуск: python -m bot.main"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot import db
from bot.config import config
from bot.handlers import admin, onboarding, steps
from bot.scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wegrow")


async def main() -> None:
    config.validate()
    await db.connect(config.database_url)
    log.info("БД подключена, схема применена")

    bot = Bot(config.bot_token)
    dp = Dispatcher()
    # Порядок важен: admin-команды и онбординг раньше общего приёма шагов.
    dp.include_router(admin.router)
    dp.include_router(onboarding.router)
    dp.include_router(steps.router)

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
