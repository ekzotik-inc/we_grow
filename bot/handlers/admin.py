"""Админ-режим P&C: /broadcast и /leaderboard. Дисквалификация — /dq <id>."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db, keyboards, notify, texts
from bot.config import config
from bot.premium_emoji import pe

router = Router()


def _is_admin(tg_id: int) -> bool:
    return tg_id in config.admin_ids


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(texts.ADMIN_PANEL, reply_markup=keyboards.admin_panel_kb())


@router.callback_query(F.data.startswith("appr:"))
async def approve_registration(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    target = int(cb.data.split(":")[1])
    p = await db.get_participant(target)
    if p is None:
        await cb.answer("Участник не найден (возможно, сбросил регистрацию).", show_alert=True)
        await cb.message.edit_reply_markup(reply_markup=None)
        return
    if p["approved_at"]:
        await cb.message.edit_reply_markup(reply_markup=None)
        return await cb.answer("Уже подтверждён.")
    await db.set_approved(target)
    await cb.message.edit_text(cb.message.html_text + f"\n\n✅ Подтверждено ({escape(cb.from_user.first_name)})")
    try:
        await cb.bot.send_message(target, texts.APPROVED, reply_markup=keyboards.main_kb())
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Подтверждено ✅")


@router.callback_query(F.data.startswith("rej:"))
async def reject_registration(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    target = int(cb.data.split(":")[1])
    p = await db.get_participant(target)
    await db.reset_participant(target)
    await cb.message.edit_text(cb.message.html_text + f"\n\n❌ Отклонено ({escape(cb.from_user.first_name)})")
    if p is not None:
        try:
            from aiogram.types import ReplyKeyboardRemove
            await cb.bot.send_message(target, texts.REJECTED, reply_markup=ReplyKeyboardRemove())
        except Exception:  # noqa: BLE001
            pass
    await cb.answer("Отклонено ❌")


@router.callback_query(F.data == "adm:board")
async def adm_board(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    await cb.message.answer(texts.render_leaderboard(teams, top, top_title="Топ-10 участников"))
    await cb.answer()


@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await cb.message.answer("Напиши текст рассылки одним сообщением (или /cancel).")
    await state.set_state(Broadcast.text)
    await cb.answer()


@router.callback_query(F.data == "adm:review")
async def adm_review(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    rows = await db.pending_reviews(10)
    if not rows:
        await cb.message.answer("🔎 На проверку ничего нет — все чисто ✅")
    else:
        lines = ["🔎 <b>На проверку P&amp;C</b>"]
        for r in rows:
            lines.append(f"• {r['entry_date']}: {escape(r['full_name'])} — "
                         f"<b>{r['steps']}</b> шагов (/dq {r['participant_id']})")
        await cb.message.answer("\n".join(lines))
    await cb.answer()


async def _stats_text() -> str:
    day = datetime.now(config.tz).date()
    submitted, active = await db.engagement(day)
    pct = round(submitted / active * 100) if active else 0
    return (
        f"📊 <b>Вовлечённость за {day}</b>\n"
        f"<blockquote>Сдали шаги: <b>{submitted}</b> из <b>{active}</b> ({pct}%)</blockquote>"
    )


@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await cb.message.answer(await _stats_text())
    await cb.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _stats_text())


class Broadcast(StatesGroup):
    text = State()


class EmojiCapture(StatesGroup):
    waiting = State()


@router.message(Command("emojiid"))
async def emojiid_start(message: Message, state: FSMContext) -> None:
    """Достаёт custom_emoji_id из присланных премиум-эмодзи (для emoji_ids.json)."""
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "Пришли одним сообщением премиум-эмодзи (спорт/бег и т.п.), которые хочешь "
        "использовать. Я верну их emoji-id для bot/emoji_ids.json.\n"
        "⚠️ Отправлять премиум-эмодзи может только аккаунт с Telegram Premium."
    )
    await state.set_state(EmojiCapture.waiting)


@router.message(EmojiCapture.waiting)
async def emojiid_capture(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    pairs: dict[str, str] = {}
    for e in entities:
        if e.type == "custom_emoji" and e.custom_emoji_id:
            pairs[e.extract_from(text)] = e.custom_emoji_id
    if not pairs:
        await message.answer(
            "Не вижу премиум-эмодзи в сообщении. Нужен Telegram Premium, "
            "чтобы их отправлять, и это должны быть именно кастомные эмодзи."
        )
        return
    snippet = json.dumps(pairs, ensure_ascii=False, indent=2)
    await message.answer(
        "Готово! Впиши эти пары в <b>bot/emoji_ids.json</b> "
        "и выставь PREMIUM_EMOJI=true:\n\n<pre>" + escape(snippet) + "</pre>"
    )


@router.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer("Напиши текст рассылки одним сообщением (или /cancel).")
    await state.set_state(Broadcast.text)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(Broadcast.text, F.text)
async def broadcast_send(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = message.text
    ids = await db.all_active_ids()
    await message.answer(f"Отправляю {len(ids)} участникам…")
    # Текст рассылки — произвольный ввод админа, шлём без разметки.
    sent = await notify.broadcast(message.bot, ids, text, parse_mode=None)
    await db.pool().execute(
        """INSERT INTO broadcasts (admin_id, text, audience, recipients)
           VALUES ($1,$2,'all',$3)""",
        message.from_user.id, text, sent,
    )
    await message.answer(f"Доставлено: {sent}/{len(ids)}.")


@router.message(Command("dq"))
async def disqualify(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /dq ID (числовой Telegram ID участника)")
        return
    target = int(parts[1])
    p = await db.get_participant(target)
    if p is None:
        await message.answer("Участник не найден.")
        return
    await db.pool().execute(
        "UPDATE participants SET disqualified_at=$2 WHERE telegram_id=$1",
        target, datetime.now(timezone.utc),
    )
    name = escape(p["full_name"])
    await message.answer(f"Дисквалифицирован: {name}. Баллы исключены из зачёта.")
    from bot.notify import notify_admins
    await notify_admins(message.bot, f"⛔ {name} дисквалифицирован администратором.")


@router.message(Command("leaderboard"))
async def leaderboard(message: Message) -> None:
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    await message.answer(render_leaderboard(teams, top, top_title="Топ участников"))
