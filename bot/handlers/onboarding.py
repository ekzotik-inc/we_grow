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

from bot import db, keyboards, settings, texts
from bot.config import config
from bot.menu import send_main_menu

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

    p = await db.get_participant(tg_id)
    if p and p["team_id"]:
        if p["approved_at"]:
            await send_main_menu(message.bot, tg_id, texts.welcome_back())
        else:
            await message.answer(texts.NOT_APPROVED_YET, reply_markup=ReplyKeyboardRemove())
        return

    await message.answer(texts.WELCOME)
    await message.answer(texts.RULES, disable_web_page_preview=True,
                         reply_markup=keyboards.consent_kb())


@router.message(Command("rules"))
@router.message(lambda m: bool(m.text) and m.text == settings.label("rules"))
async def cmd_rules(message: Message) -> None:
    await message.answer(texts.RULES, disable_web_page_preview=True)


@router.message(Command("help"))
@router.message(lambda m: bool(m.text) and m.text == settings.label("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, disable_web_page_preview=True,
                         reply_markup=keyboards.feedback_kb())


@router.message(Command("feedback"))
@router.message(lambda m: bool(m.text) and m.text == settings.label("feedback"))
async def cmd_feedback(message: Message) -> None:
    await message.answer(texts.FEEDBACK, reply_markup=keyboards.feedback_kb())


@router.message(lambda m: bool(m.text) and m.text == settings.label("board"))
async def menu_board(message: Message) -> None:
    # Лидерборд прямо в чате + inline-кнопка открыть в приложении.
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    await message.answer(
        texts.render_leaderboard(teams, top, top_title="Топ-10 участников"),
        reply_markup=keyboards.open_app_kb("🏆 Открыть лидерборд"),
    )


@router.message(lambda m: bool(m.text) and m.text == settings.label("progress"))
async def menu_progress(message: Message) -> None:
    kb = keyboards.open_app_kb("📊 Открыть мой прогресс")
    if kb:
        await message.answer(texts.OPEN_PROGRESS, reply_markup=kb)
    else:
        await message.answer(texts.stepy("Открой приложение кнопкой меню слева от поля ввода 🌱"))


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
    await db.set_profile(cb.from_user.id, data["full_name"], is_asr, cb.from_user.username)
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
            await cb.message.answer(texts.TEAM_FULL, reply_markup=keyboards.teams_kb(teams))
            await cb.answer()
            return

    await db.set_team(cb.from_user.id, team["id"])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.PENDING.format(team=team["name"]),
                            reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await cb.answer()

    # Пуш админам с подробной карточкой и кнопками подтверждения.
    from bot.notify import notify_admins
    p = await db.get_participant(cb.from_user.id)
    await notify_admins(cb.bot, texts.admin_new_registration(p, team["name"]),
                        reply_markup=keyboards.approve_kb(cb.from_user.id))
