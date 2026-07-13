"""Онбординг: /start → правила+согласие → анкета → команда."""
from __future__ import annotations

import random
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from bot import db, keyboards, texts
from bot.config import config

router = Router()


class Onboarding(StatesGroup):
    name = State()
    asr = State()
    team = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg_id = message.from_user.id
    await db.upsert_participant_start(tg_id)
    # Админов помечаем ролью по конфигу.
    if tg_id in config.admin_ids:
        await db.set_role(tg_id, "admin")

    is_admin = tg_id in config.admin_ids
    p = await db.get_participant(tg_id)
    if p and p["consent_at"] and p["team_id"]:
        await message.answer("С возвращением, чемпион! 👟 Готов к новым шагам?",
                             reply_markup=keyboards.main_kb(is_admin))
        return

    await message.answer(texts.WELCOME)
    await message.answer(texts.RULES, disable_web_page_preview=True,
                         reply_markup=keyboards.consent_kb())


@router.message(Command("rules"))
@router.message(F.text == texts.MENU_RULES)
async def cmd_rules(message: Message) -> None:
    await message.answer(texts.RULES, disable_web_page_preview=True)


@router.message(Command("help"))
@router.message(F.text == texts.MENU_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, disable_web_page_preview=True)


@router.message(F.text == texts.MENU_BOARD)
async def menu_board(message: Message) -> None:
    # Фолбэк, если Mini App недоступен: лидерборд прямо в чате.
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    await message.answer(texts.render_leaderboard(teams, top, top_title="Топ-10 участников"))


@router.message(F.text == texts.MENU_PROGRESS)
async def menu_progress(message: Message) -> None:
    await message.answer("📊 Открой «Мой прогресс» кнопкой меню слева от поля ввода 🌱")


@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext) -> None:
    await state.clear()
    if await db.get_participant(message.from_user.id) is None:
        await message.answer(texts.RESET_NOTHING)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=texts.RESET_YES, callback_data="reset_yes"),
        InlineKeyboardButton(text=texts.RESET_NO, callback_data="reset_no"),
    ]])
    await message.answer(texts.RESET_CONFIRM, reply_markup=kb)


@router.callback_query(F.data == "reset_no")
async def reset_no(cb: CallbackQuery) -> None:
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.RESET_CANCELLED)
    await cb.answer()


@router.callback_query(F.data == "reset_yes")
async def reset_yes(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await db.reset_participant(cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.RESET_DONE, reply_markup=ReplyKeyboardRemove())
    await cb.answer()


@router.callback_query(F.data == "consent")
async def on_consent(cb: CallbackQuery, state: FSMContext) -> None:
    await db.set_consent(cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.ASK_NAME)
    await state.set_state(Onboarding.name)
    await cb.answer()


@router.message(Onboarding.name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    await state.update_data(full_name=message.text.strip())
    await message.answer(texts.ASK_ASR, reply_markup=keyboards.asr_kb())
    await state.set_state(Onboarding.asr)


@router.callback_query(Onboarding.asr, F.data.startswith("asr:"))
async def on_asr(cb: CallbackQuery, state: FSMContext) -> None:
    is_asr = cb.data.split(":")[1] == "1"
    data = await state.get_data()
    await db.set_profile(cb.from_user.id, data["full_name"], is_asr)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.FIT_LINKS, disable_web_page_preview=True)

    teams = await db.open_teams()
    await cb.message.answer(texts.ASK_TEAM, reply_markup=keyboards.teams_kb(teams))
    await state.set_state(Onboarding.team)
    await cb.answer()


@router.callback_query(Onboarding.team, F.data.startswith("team:"))
async def on_team(cb: CallbackQuery, state: FSMContext) -> None:
    choice = cb.data.split(":")[1]
    teams = await db.open_teams()
    if not teams:
        await cb.answer("Свободных мест нет — сообщите P&C.", show_alert=True)
        return

    if choice == "random":
        team = random.choice(teams)
    else:
        team = next((t for t in teams if t["id"] == int(choice)), None)
        if team is None:  # место заняли, пока выбирал
            await cb.message.answer("Эта команда только что заполнилась, выбери другую:",
                                    reply_markup=keyboards.teams_kb(teams))
            await cb.answer()
            return

    await db.set_team(cb.from_user.id, team["id"])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.ONBOARDED.format(team=team["name"]),
                            reply_markup=keyboards.main_kb(cb.from_user.id in config.admin_ids))
    await state.clear()
    await cb.answer()

    # Уведомляем P&C о новой регистрации.
    from bot.notify import notify_admins
    p = await db.get_participant(cb.from_user.id)
    await notify_admins(cb.bot, f"🆕 Регистрация: {escape(p['full_name'])} → команда {team['name']}")
