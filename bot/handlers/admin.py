"""Админ-режим P&C: /broadcast и /leaderboard. Дисквалификация — /dq <id>."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import db, notify
from bot.config import config
from bot.premium_emoji import pe

router = Router()


def _is_admin(tg_id: int) -> bool:
    return tg_id in config.admin_ids


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
    lines = [f"{pe('📊')} <b>Команды:</b>"]
    for i, t in enumerate(teams, 1):
        prefix = pe("👑") if i == 1 else f"{i}."
        lines.append(f"{prefix} {escape(t['name'])} — {t['points']}")
    lines.append(f"\n{pe('👣')} <b>Топ участников:</b>")
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. {escape(p['full_name'] or '—')} — {p['points']}")
    await message.answer("\n".join(lines))
