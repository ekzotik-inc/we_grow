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


def _today():
    return datetime.now(config.tz).date()


def _parse_steps(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    val = int(digits)
    return val if 0 < val < 200_000 else None


async def _require_approved(message: Message):
    p = await db.get_participant(message.from_user.id)
    if p is None or not p["team_id"]:
        await message.answer("Сначала зарегистрируйся: /start 🌱")
        return None
    if not p["approved_at"]:
        await message.answer(texts.NOT_APPROVED_YET)
        return None
    return p


@router.message(lambda m: bool(m.text) and m.text == settings.label("steps"))
async def ask_steps(message: Message, state: FSMContext) -> None:
    if not await _require_approved(message):
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


@router.message(Steps.screenshot, F.photo)
async def on_screenshot(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    steps = data.get("steps")
    await state.clear()
    if steps is None:
        await message.answer(texts.STEP1_NUMBER)
        await state.set_state(Steps.number)
        return
    tg_id = message.from_user.id
    file_id = message.photo[-1].file_id
    entry_id = await db.save_submission(tg_id, _today(), steps, file_id)
    await message.answer(texts.STEP3_WAIT.format(steps=steps))

    # Уведомляем P&C: скриншот + карточка + кнопки модерации.
    from bot import notify
    entry = await db.entry_by_id(entry_id)
    await notify.admins_submission(message.bot, file_id, texts.admin_new_submission(entry),
                                   keyboards.moderate_kb(entry_id))


@router.message(Steps.screenshot)
async def need_screenshot(message: Message) -> None:
    await message.answer(texts.STEP2_NEED_PHOTO)
