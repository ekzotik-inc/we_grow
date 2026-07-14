"""Админ-режим P&C: /admin панель, подтверждение регистраций, /leaderboard,
/stats, /dq, /emojiid. Модерация результатов и настройки — в admin_settings."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot import db, keyboards, notify, settings, texts
from bot.config import config
from bot.premium_emoji import pe

router = Router()


def _is_admin(tg_id: int) -> bool:
    return settings.is_admin(tg_id)


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(texts.ADMIN_PANEL, reply_markup=keyboards.admin_panel_kb())


async def _send_export(bot, chat_id: int) -> None:
    from aiogram.types import BufferedInputFile
    from bot.export import build_workbook
    data, name = await build_workbook()
    await bot.send_document(chat_id, BufferedInputFile(data, filename=name),
                            caption="📥 Выгрузка данных марафона")


@router.callback_query(F.data == "adm:export")
async def adm_export(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await cb.answer("Готовлю файл…")
    await _send_export(cb.bot, cb.from_user.id)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _send_export(message.bot, message.from_user.id)


@router.callback_query(F.data == "adm:design")
async def adm_design(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await cb.message.edit_text("⚙️ <b>Оформление</b>\nМедиа меню, подписи и иконки кнопок.",
                               reply_markup=keyboards.design_panel_kb())
    await cb.answer()


@router.callback_query(F.data == "adm:back")
async def adm_back(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await cb.message.edit_text(texts.ADMIN_PANEL, reply_markup=keyboards.admin_panel_kb())
    await cb.answer()


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
        from bot.menu import send_main_menu
        await send_main_menu(cb.bot, target, texts.APPROVED)
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


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


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
    await db.set_disqualified(target)
    name = escape(p["full_name"])
    await message.answer(f"Дисквалифицирован: {name}. Баллы исключены из зачёта.")
    try:
        await message.bot.send_message(target, texts.DISQUALIFIED_NOTICE,
                                       reply_markup=ReplyKeyboardRemove())
    except Exception:  # noqa: BLE001
        pass
    from bot.notify import notify_admins
    await notify_admins(message.bot, f"⛔ {name} дисквалифицирован администратором.")


def _parse_id_arg(text: str) -> int | None:
    parts = (text or "").split()
    if len(parts) == 2 and parts[1].lstrip("-").isdigit():
        return int(parts[1])
    return None


@router.message(Command("addadmin"))
async def add_admin_cmd(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    tid = _parse_id_arg(message.text)
    if tid is None:
        await message.answer("Использование: /addadmin ID (числовой Telegram ID)")
        return
    await settings.add_admin(tid)
    await db.set_role(tid, "admin")  # если у пользователя уже есть запись участника
    await message.answer(
        f"✅ Пользователь <code>{tid}</code> теперь администратор.\n"
        "Ему нужно нажать /start, чтобы в меню появились админ-команды.")


@router.message(Command("deladmin"))
async def del_admin_cmd(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    tid = _parse_id_arg(message.text)
    if tid is None:
        await message.answer("Использование: /deladmin ID")
        return
    if tid in config.admin_ids:
        await message.answer("Этот админ задан через ADMIN_IDS (env) — его можно убрать "
                             "только там. Доп-админов снимаю без проблем.")
        return
    await settings.remove_admin(tid)
    await message.answer(f"✅ Пользователь <code>{tid}</code> больше не администратор.")


@router.message(Command("delete"))
async def delete_user_cmd(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    tid = _parse_id_arg(message.text)
    if tid is None:
        await message.answer("Использование: /delete ID (полностью удаляет данные участника)")
        return
    p = await db.get_participant(tid)
    if p is None:
        await message.answer("Участник с таким ID не найден в базе.")
        return
    await db.reset_participant(tid)
    name = escape(p["full_name"] or str(tid))
    await message.answer(f"🗑 Данные участника <b>{name}</b> (<code>{tid}</code>) полностью удалены.")


@router.message(Command("leaderboard"))
async def leaderboard(message: Message) -> None:
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    await message.answer(texts.render_leaderboard(teams, top, top_title="Топ участников"))
