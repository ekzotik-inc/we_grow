"""Приём шагов через модерацию P&C.

Флоу участника: шаг 1 — число шагов, шаг 2 — скриншот из Fitbit,
шаг 3 — ожидание. Результат уходит на модерацию (status=pending) и
засчитывается только после принятия сотрудником P&C.
"""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import db, keyboards, settings, texts
from bot.config import config

router = Router()


class Steps(StatesGroup):
    number = State()
    screenshot = State()


class Weekly(StatesGroup):
    screenshot = State()


def _today():
    return datetime.now(config.tz).date()


DEADLINE = (23, 55)


def _day_closed() -> bool:
    """После 23:55 приём за текущий день закрыт (правило «до 23:55»)."""
    now = datetime.now(config.tz)
    return (now.hour, now.minute) >= DEADLINE


def _parse_steps(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    val = int(digits)
    return val if 0 < val < 200_000 else None


async def _require_approved(message: Message):
    p = await db.get_participant(message.from_user.id)
    if p is None or not p["team_id"]:
        await message.answer(texts.NEED_REGISTER)
        return None
    if not p["approved_at"]:
        await message.answer(texts.NOT_APPROVED_YET)
        return None
    return p


@router.message(lambda m: bool(m.text) and m.text == settings.label("steps"))
async def ask_steps(message: Message, state: FSMContext) -> None:
    if not await _require_approved(message):
        return
    today = _today()
    if today < config.marathon_start:
        await message.answer(texts.marathon_not_started(config.marathon_start))
        return
    if today > config.marathon_end:
        await message.answer(texts.MARATHON_FINISHED)
        return
    if _day_closed():
        await message.answer(texts.DAY_CLOSED)
        return
    existing = await db.get_entry(message.from_user.id, _today())
    if existing and existing["status"] == "accepted":
        await message.answer(texts.ALREADY_ACCEPTED.format(steps=existing["steps"]))
        return
    if existing and existing["status"] == "pending":
        await message.answer(texts.ALREADY_PENDING.format(steps=existing["steps"]))
        return
    # нет записи или отклонена — начинаем отправку
    await message.answer(texts.STEP1_NUMBER)
    await state.set_state(Steps.number)


@router.message(Steps.number, F.text)
async def on_number(message: Message, state: FSMContext) -> None:
    steps = _parse_steps(message.text)
    if steps is None:
        await message.answer(texts.STEP1_BAD)
        return
    await state.update_data(steps=steps)
    await message.answer(texts.STEP2_SCREENSHOT.format(steps=steps))
    await state.set_state(Steps.screenshot)


@router.message(Steps.screenshot, F.photo | F.document)
async def on_screenshot(message: Message, state: FSMContext) -> None:
    # Скриншот может прийти как фото (из галереи) или как файл-изображение.
    if message.photo:
        file_id = message.photo[-1].file_id
        unique_id = message.photo[-1].file_unique_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id = "doc:" + message.document.file_id  # префикс — чтобы переслать как документ
        unique_id = message.document.file_unique_id
    else:
        await message.answer(texts.STEP2_NEED_PHOTO)
        return
    data = await state.get_data()
    steps = data.get("steps")
    await state.clear()
    if steps is None:
        await message.answer(texts.STEP1_NUMBER)
        await state.set_state(Steps.number)
        return
    if _day_closed():
        # Дедлайн мог наступить, пока участник искал скриншот.
        await message.answer(texts.DAY_CLOSED)
        return
    tg_id = message.from_user.id
    entry_id = await db.save_submission(tg_id, _today(), steps, file_id, unique_id)
    await message.answer(texts.STEP3_WAIT.format(steps=steps))

    # Уведомляем P&C: скриншот + карточка + кнопки модерации.
    from bot import notify
    entry = await db.entry_by_id(entry_id)
    caption = texts.admin_new_submission(entry)
    dup = await db.duplicate_screenshot(unique_id, entry_id)
    if dup:
        caption += texts.admin_duplicate_warn(dup)
    await notify.admins_submission(message.bot, file_id, caption,
                                   keyboards.moderate_kb(entry_id))


@router.message(Steps.screenshot)
async def need_screenshot(message: Message) -> None:
    await message.answer(texts.STEP2_NEED_PHOTO)


# ---- Еженедельный отчёт (вс 22:00–23:55) -----------------------------------

WEEKLY_OPEN = (22, 0)


def _weekly_window() -> str:
    """closed_day | too_early | open | closed — статус окна приёма отчётов."""
    now = datetime.now(config.tz)
    if now.weekday() != 6:                      # не воскресенье
        return "closed_day"
    if (now.hour, now.minute) < WEEKLY_OPEN:
        return "too_early"
    if (now.hour, now.minute) >= DEADLINE:      # 23:55
        return "closed"
    return "open"


def _this_monday():
    today = datetime.now(config.tz).date()
    from datetime import timedelta
    return today - timedelta(days=today.weekday())


@router.message(lambda m: bool(m.text) and m.text == settings.label("weekly"))
async def ask_weekly(message: Message, state: FSMContext) -> None:
    if not await _require_approved(message):
        return
    today = _today()
    if today < config.marathon_start:
        await message.answer(texts.marathon_not_started(config.marathon_start))
        return
    if today > config.marathon_end:
        await message.answer(texts.MARATHON_FINISHED)
        return
    w = _weekly_window()
    if w == "closed_day":
        await message.answer(texts.WEEKLY_ONLY_SUNDAY)
        return
    if w == "too_early":
        await message.answer(texts.WEEKLY_TOO_EARLY)
        return
    if w == "closed":
        await message.answer(texts.WEEKLY_CLOSED)
        return
    await message.answer(texts.WEEKLY_ASK_SHOT)
    await state.set_state(Weekly.screenshot)


@router.message(Weekly.screenshot, F.photo | F.document)
async def on_weekly_shot(message: Message, state: FSMContext) -> None:
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id = "doc:" + message.document.file_id
    else:
        await message.answer(texts.WEEKLY_NEED_SHOT)
        return
    if _weekly_window() != "open":
        await state.clear()
        await message.answer(texts.WEEKLY_CLOSED)
        return
    tg_id = message.from_user.id
    monday = _this_monday()
    already = await db.has_weekly_report(tg_id, monday)
    await db.save_weekly_report(tg_id, monday, file_id)
    await state.clear()
    await message.answer(texts.WEEKLY_UPDATED if already else texts.WEEKLY_SAVED)

    # Копия — P&C (информационно, без модерации).
    from bot import notify
    p = await db.get_participant(tg_id)
    team = await db.team_name(p["team_id"]) if p["team_id"] else None
    await notify.admins_submission(message.bot, file_id,
                                   texts.admin_weekly_report(p, team, monday), None)


@router.message(Weekly.screenshot)
async def weekly_need_shot(message: Message) -> None:
    await message.answer(texts.WEEKLY_NEED_SHOT)
