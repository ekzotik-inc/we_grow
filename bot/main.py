"""Точка входа бота. Запуск: python -m bot.main"""
from __future__ import annotations

import asyncio
import logging

from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramConflictError

from bot import commands, db, settings
from bot.config import config
from bot.handlers import (activities, admin, admin_settings, challenge, flashmob,
                          onboarding, steps)
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


async def _one_time_migrations() -> None:
    """Разовые правки данных под обновлённые правила WE GROW. Каждая
    помечается флагом в settings и при следующих стартах не повторяется."""
    if not settings.get("migr_scale_20k"):
        # Шкала дополнена ступенью 20 000+ → 4 балла: пересчитываем уже
        # принятые дни (с учётом челленджей), затем серии/бонусы не меняются —
        # они зависят от шагов, а не от баллов.
        changed = await db.rescore_accepted_entries()
        await settings.set("migr_scale_20k", "1")
        log.info("Миграция шкалы 20 000+ → 4: пересчитано записей: %s", changed)
    if not settings.get("migr_team_size_5"):
        # Команда — ровно 5 человек: стандартная вместимость 10 → 5.
        # Вручную заданные вместимости (не 10) не трогаем.
        n = await db.pool().execute(
            "UPDATE teams SET capacity=$1 WHERE capacity=10", db.TEAM_SIZE)
        await settings.set("migr_team_size_5", "1")
        over = [t for t in await db.teams_with_capacity() if t["taken"] > t["capacity"]]
        log.info("Миграция размера команды → %s: %s", db.TEAM_SIZE, n)
        for t in over:
            log.warning("Команда «%s» переполнена: %s/%s — состав правит P&C",
                        t["name"], t["taken"], t["capacity"])


async def main() -> None:
    config.validate()
    await _connect_db_retry()
    await settings.load()
    await _one_time_migrations()
    # Пол по ФИО — для раздельных топов. Трогает только тех, у кого он пуст,
    # поэтому ручные правки админов переживают перезапуск.
    filled = await db.backfill_genders()
    log.info("БД подключена, схема применена, настройки загружены "
             "(пол определён у %s новых участников)", filled)
    # Печатаем живую конфигурацию: по этой строке в логах Render сразу видно,
    # с какой таймзоной и датами реально работает бот.
    today = datetime.now(config.tz).date()
    log.info("Конфигурация: TZ=%s, сегодня=%s, марафон %s — %s (%s), админов=%s",
             config.tz_name, today, config.marathon_start, config.marathon_end,
             "идёт" if config.marathon_start <= today <= config.marathon_end
             else ("ещё не начался" if today < config.marathon_start else "завершён"),
             len(settings.admin_ids()))

    # HTML по умолчанию — нужно для премиум-эмодзи (<tg-emoji>) и <b>.
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    # Анимированные эмодзи из набора — во всех исходящих HTML-сообщениях.
    from bot.premium_emoji import EmojiMiddleware
    bot.session.middleware(EmojiMiddleware())
    dp = Dispatcher()
    # Онбординг первым: его команды (/start, /reset, /help, /rules, /feedback)
    # и кнопки меню должны срабатывать ВСЕГДА — даже когда пользователь застрял
    # в каком-то сценарии (ввод рассылки, эмодзи и т.п.). Приём шагов — последним.
    dp.include_router(onboarding.router)
    dp.include_router(admin.router)
    dp.include_router(admin_settings.router)
    dp.include_router(challenge.router)
    dp.include_router(flashmob.router)
    dp.include_router(activities.router)
    dp.include_router(steps.router)
    dp.errors.register(_on_error)

    # Блокировка дисквалифицированных участников (кроме админов).
    from bot.middleware import BlockDisqualifiedMiddleware
    block_mw = BlockDisqualifiedMiddleware()
    dp.message.middleware(block_mw)
    dp.callback_query.middleware(block_mw)

    # Постоянная кнопка меню открывает Mini App (если задан URL в настройках/env).
    # Всё, что ниже до polling, — необязательное оформление: оборачиваем, чтобы
    # сбой Telegram не помешал боту начать принимать сообщения.
    webapp_url = settings.webapp_url()
    if webapp_url:
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=webapp_url))
            )
            log.info("Кнопка меню Mini App: %s", webapp_url)
        except Exception as e:  # noqa: BLE001
            log.warning("не удалось поставить кнопку меню Mini App: %s", e)

    # Премиум-эмодзи: сохранённый админом набор (/emojipack) или файл, но
    # только ID, которые Telegram подтвердил как премиум-эмодзи.
    try:
        import json as _json
        from bot import premium_emoji
        saved = settings.get("emoji_pack")
        if saved:
            premium_emoji.apply_pack(_json.loads(saved))
        else:
            await premium_emoji.validate(bot)
        st = premium_emoji.STATUS
        log.info("Премиум-эмодзи (%s): подтверждено %s из %s, наборы: %s",
                 st["source"], st["valid"], st["total"], ", ".join(st["sets"]) or "—")
    except Exception as e:  # noqa: BLE001
        log.warning("проверка премиум-эмодзи не удалась: %s", e)

    try:
        from bot import brand
        await brand.apply_once(bot)
    except Exception as e:  # noqa: BLE001
        log.warning("оформление WE GROW не применилось: %s", e)

    await commands.setup_all(bot)
    log.info("Команды меню настроены (админов: %s)", len(settings.admin_ids()))

    scheduler = setup_scheduler(bot)
    scheduler.start()
    log.info("Планировщик запущен")

    try:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:  # noqa: BLE001
            log.warning("delete_webhook не прошёл (%s) — продолжаем", e)
        me = await bot.get_me()
        log.info("Старт polling: @%s (id %s)", me.username, me.id)
        await dp.start_polling(bot)
    except TelegramConflictError:
        # Telegram отдаёт getUpdates только одному процессу. Обычно это второй
        # запущенный экземпляр (локальный запуск или зависший старый деплой).
        log.error("КОНФЛИКТ: бота уже опрашивает другой процесс. "
                  "Остановите лишний экземпляр — этот молчит, пока их двое.")
        raise
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
