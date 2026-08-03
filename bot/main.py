"""Точка входа бота. Запуск: python -m bot.main"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot import commands, db, settings
from bot.config import config
from bot.handlers import admin, admin_settings, challenge, flashmob, onboarding, steps
from bot.scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wegrow")


async def _connect_db_retry(attempts: int = 6) -> None:
    """Подключение к БД с ретраями (БД может подниматься дольше бота)."""
    for i in range(1, attempts + 1):
        try:
            await db.connect(config.database_url)
            return
        except Exception as e:  # noqa: BLE001
            wait = min(2 * i, 15)
            log.warning("Не удалось подключиться к БД (%s/%s): %s — повтор через %sс", i, attempts, e, wait)
            await asyncio.sleep(wait)
    raise SystemExit("БД недоступна — проверь DATABASE_URL")


async def _on_error(event) -> bool:
    """Глобальный обработчик: логирует любую ошибку хендлера и мягко отвечает,
    не роняя polling."""
    log.exception("Необработанная ошибка: %s", getattr(event, "exception", None))
    try:
        upd = getattr(event, "update", None)
        if upd is not None and upd.message:
            await upd.message.answer(
                "Ой, что-то пошло не так 🌱 Попробуй ещё раз или напиши в «Обратную связь».")
        elif upd is not None and upd.callback_query:
            await upd.callback_query.answer("Что-то пошло не так, попробуй ещё раз.", show_alert=True)
    except Exception:  # noqa: BLE001
        pass
    return True


async def main() -> None:
    config.validate()
    await _connect_db_retry()
    await settings.load()
    log.info("БД подключена, схема применена, настройки загружены")

    # HTML по умолчанию — нужно для премиум-эмодзи (<tg-emoji>) и <b>.
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    # Онбординг первым: его команды (/start, /reset, /help, /rules, /feedback)
    # и кнопки меню должны срабатывать ВСЕГДА — даже когда пользователь застрял
    # в каком-то сценарии (ввод рассылки, эмодзи и т.п.). Приём шагов — последним.
    dp.include_router(onboarding.router)
    dp.include_router(admin.router)
    dp.include_router(admin_settings.router)
    dp.include_router(challenge.router)
    dp.include_router(flashmob.router)
    dp.include_router(steps.router)
    dp.errors.register(_on_error)

    # Блокировка дисквалифицированных участников (кроме админов).
    from bot.middleware import BlockDisqualifiedMiddleware
    block_mw = BlockDisqualifiedMiddleware()
    dp.message.middleware(block_mw)
    dp.callback_query.middleware(block_mw)

    # Постоянная кнопка меню открывает Mini App (если задан URL в настройках/env).
    webapp_url = settings.webapp_url()
    if webapp_url:
        from aiogram.types import MenuButtonWebApp, WebAppInfo
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=webapp_url))
        )
        log.info("Кнопка меню Mini App: %s", webapp_url)

    await commands.setup_all(bot)
    log.info("Команды меню настроены (админов: %s)", len(settings.admin_ids()))

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
