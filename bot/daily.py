"""Картинки дня WE GROW: 11 слайдов (assets/daily/NN.png) в течение марафона.

Расписание задаётся СМЕЩЕНИЕМ от первого дня марафона (config.marathon_start),
а не датами: если даты поменяются, картинки поедут вместе с ними. Слайды
распределены по 2 неделям марафона (02.11 пн — 15.11 вс, 14 дней): «Стартуем!»
в первый день, затем советы почти каждый день, «Выходной на ногах» — на
последнюю субботу, финальный — в последний день. При смене длительности
марафона смещения нужно пересмотреть (смещение > длины — слайд не уйдёт).

Отправка — job `send_daily_card` в 09:00. Файл загружается в Telegram один
раз, дальше рассылается по file_id (кеш в settings `daily_fid_NN`). Отметка
об отправке — `daily_sent_NN` (дата и число получателей), повторно за день
слайд не уходит. Если файла слайда нет — день пропускается с записью в лог.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile

from bot import db, settings
from bot.config import config
from bot.texts import stepy

log = logging.getLogger(__name__)

DIR = Path(__file__).resolve().parent.parent / "assets" / "daily"

# слайд → (смещение от старта в днях, заголовок, реплика Stepy)
SLIDES: dict[int, tuple[int, str, str]] = {
    1: (0, "Стартуем!",
        "Второй блок марафона — <b>WE GROW</b> 🚀 Шагаем вместе: каждый день присылай "
        "число шагов и скриншот из Google Health до <b>23:55</b>. Твои баллы — это "
        "вклад в средний результат команды. Поехали!"),
    2: (1, "Время прогулки",
        "Небольшая прогулка сегодня? Выбери удобный маршрут — даже 20 минут дают "
        "заметную прибавку к шагам 🌿"),
    3: (2, "Пешком до кофе",
        "За любимым кофе можно пройтись пешком ☕ Шаги + вкусный повод — идеальное "
        "сочетание."),
    4: (4, "Пауза для шагов",
        "Отложи дела ненадолго: пройдись и возвращайся с новыми силами 💪"),
    5: (6, "Вместе веселее",
        "Позови коллегу на прогулку — и шаги в копилку, и пообщаетесь 🤝"),
    6: (7, "День пятый",
        "Новый день — новые шаги! Не забудь сдать результат до 23:55 👟"),
    7: (8, "В своём темпе",
        "Выбирай комфортный темп и посильную дистанцию: главное — регулярность, "
        "а не рекорды 🌱"),
    8: (9, "Вечер на ходу",
        "После рабочего дня найдётся время для прогулки? Вечерние шаги тоже "
        "считаются 🌇"),
    9: (11, "Шаги по пути",
        "До магазина или до парка — пройдись, если удобно 🛍 Каждый маршрут — "
        "это шаги для команды."),
    10: (12, "Выходной на ногах",
         "Прогулка в хорошей компании — отличный план на выходной ⛰"),
    11: (13, "Разговор на ходу",
         "Финишная прямая! 🏁 Созвонись с другом во время спокойной прогулки — "
         "и не забудь сдать шаги за последний день до 23:55."),
}


def path(n: int) -> Path:
    return DIR / f"{n:02d}.png"


def day_of(n: int) -> date:
    return config.marathon_start + timedelta(days=SLIDES[n][0])


def slides_for(day: date) -> list[int]:
    return [n for n in SLIDES if day_of(n) == day]


def caption(n: int) -> str:
    return stepy(SLIDES[n][2])


def sent_info(n: int) -> str | None:
    return settings.get(f"daily_sent_{n:02d}")


async def _send_one(bot: Bot, chat_id: int, n: int) -> bool:
    """Отправка одному чату; первый успешный аплоад кеширует file_id."""
    fid = settings.get(f"daily_fid_{n:02d}")
    try:
        msg = await bot.send_photo(chat_id, fid or FSInputFile(path(n)), caption=caption(n))
        if not fid and msg is not None and getattr(msg, "photo", None):
            await settings.set(f"daily_fid_{n:02d}", msg.photo[-1].file_id)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await _send_one(bot, chat_id, n)
    except Exception as e:  # noqa: BLE001 — заблокировал бота и т.п.
        log.warning("daily card %s to %s failed: %s", n, chat_id, e)
        return False


async def send_preview(bot: Bot, chat_id: int, n: int) -> bool:
    if not path(n).exists():
        return False
    return await _send_one(bot, chat_id, n)


async def broadcast_card(bot: Bot, n: int) -> int:
    ids = await db.all_active_ids()
    if not ids:
        return 0
    # Первый получатель — последовательно, чтобы закешировать file_id и не
    # загружать файл в Telegram сотни раз.
    sent = int(await _send_one(bot, ids[0], n))
    rest = ids[1:]
    for i in range(0, len(rest), 25):
        res = await asyncio.gather(*(_send_one(bot, cid, n) for cid in rest[i:i + 25]))
        sent += sum(res)
        if i + 25 < len(rest):
            await asyncio.sleep(1.0)
    return sent


async def send_daily_card(bot: Bot) -> None:
    """09:00 — картинка дня по расписанию SLIDES."""
    today = datetime.now(config.tz).date()
    for n in slides_for(today):
        if sent_info(n):
            continue
        if not path(n).exists():
            log.warning("Картинка дня %02d не найдена (%s) — пропускаю", n, path(n))
            continue
        cnt = await broadcast_card(bot, n)
        await settings.set(f"daily_sent_{n:02d}", f"{today.isoformat()}:{cnt}")
        log.info("Картинка дня %02d «%s» отправлена: %s", n, SLIDES[n][1], cnt)
