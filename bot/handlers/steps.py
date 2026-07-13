"""Приём шагов: скрин или число → подтверждение → начисление → обратная связь.

OCR — вторая итерация. Сейчас: если пришло фото, сохраняем file_id и просим
ввести число вручную; если пришло число — подтверждаем сразу.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from backend.scoring import needs_review, points_for_steps, update_streak
from bot import db, keyboards, texts
from bot.config import config

router = Router()


class Steps(StatesGroup):
    waiting_number = State()


def _today():
    return datetime.now(config.tz).date()


def _parse_steps(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    val = int(digits)
    return val if 0 < val < 200_000 else None


async def _require_approved(message: Message) -> bool:
    """Пускаем к приёму шагов только подтверждённых участников."""
    p = await db.get_participant(message.from_user.id)
    if p is None or not p["team_id"]:
        await message.answer("Сначала зарегистрируйся: /start 🌱")
        return False
    if not p["approved_at"]:
        await message.answer(texts.NOT_APPROVED_YET)
        return False
    return True


@router.message(F.text == texts.STEPS_BUTTON)
async def ask_steps(message: Message, state: FSMContext) -> None:
    if not await _require_approved(message):
        return
    existing = await db.get_entry(message.from_user.id, _today())
    if existing:
        await message.answer(texts.ALREADY_TODAY.format(steps=existing["steps"]))
        return
    await message.answer(texts.ASK_STEPS_PHOTO)
    await state.set_state(Steps.waiting_number)


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    # Сохраняем скрин как доказательство, число просим ввести вручную (OCR — later).
    file_id = message.photo[-1].file_id
    await state.update_data(screenshot=file_id)
    await message.answer(texts.ASK_MANUAL)
    await state.set_state(Steps.waiting_number)


@router.message(Steps.waiting_number, F.text)
async def on_number(message: Message, state: FSMContext) -> None:
    steps = _parse_steps(message.text)
    if steps is None:
        await message.answer(texts.ASK_MANUAL)
        return
    await state.update_data(steps=steps)
    await message.answer(texts.CONFIRM_STEPS.format(steps=steps),
                         reply_markup=keyboards.confirm_steps_kb(steps))


@router.callback_query(F.data == "steps_fix")
async def on_fix(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.ASK_MANUAL)
    await state.set_state(Steps.waiting_number)
    await cb.answer()


@router.callback_query(F.data.startswith("steps_ok:"))
async def on_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    tg_id = cb.from_user.id
    day = _today()
    p = await db.get_participant(tg_id)
    if p is None or not p["approved_at"]:
        await cb.answer("Заявка ещё не подтверждена P&C.", show_alert=True)
        await state.clear()
        return
    if await db.get_entry(tg_id, day):
        await cb.answer("Уже засчитано на сегодня.", show_alert=True)
        await state.clear()
        return

    steps = int(cb.data.split(":")[1])
    data = await state.get_data()
    screenshot = data.get("screenshot")

    points = points_for_steps(steps)
    review = needs_review(steps)
    upd = update_streak(await db.get_streak(tg_id), day, steps)

    await db.save_entry_and_streak(
        tg_id, day, steps, points,
        source="manual", screenshot_file_id=screenshot,
        needs_review=review, new_streak=upd.state,
    )

    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.feedback(steps, points, upd))
    await state.clear()
    await cb.answer()

    if review:
        from bot.notify import notify_admins
        p = await db.get_participant(tg_id)
        await notify_admins(cb.bot, f"⚠️ Проверка: {escape(p['full_name'])} прислал {steps} шагов (&gt;30k).")
