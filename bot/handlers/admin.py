"""Админ-режим P&C: /broadcast и /leaderboard. Дисквалификация — /dq <id>."""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import db, notify
from bot.config import config

router = Router()


def _is_admin(tg_id: int) -> bool:
    return tg_id in config.admin_ids


class Broadcast(StatesGroup):
    text = State()


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
    sent = await notify.broadcast(message.bot, ids, text)
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
        await message.answer("Использование: /dq <telegram_id>")
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
    await message.answer(f"Дисквалифицирован: {p['full_name']}. Баллы исключены из зачёта.")
    from bot.notify import notify_admins
    await notify_admins(message.bot, f"⛔ {p['full_name']} дисквалифицирован администратором.")


@router.message(Command("leaderboard"))
async def leaderboard(message: Message) -> None:
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    lines = ["🏆 *Команды:*"]
    for i, t in enumerate(teams, 1):
        lines.append(f"{i}. {t['name']} — {t['points']}")
    lines.append("\n👟 *Топ участников:*")
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. {p['full_name'] or '—'} — {p['points']}")
    await message.answer("\n".join(lines), parse_mode="Markdown")
