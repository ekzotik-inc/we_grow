"""Клавиатуры."""
from __future__ import annotations

import asyncpg
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.config import config


def consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.CONSENT_BUTTON, callback_data="consent")]
    ])


def asr_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да ✅", callback_data="asr:1"),
        InlineKeyboardButton(text="Нет", callback_data="asr:0"),
    ]])


def teams_kb(teams: list[asyncpg.Record]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in teams:
        b.button(text=f"{t['name']} — {t['taken']}/{t['capacity']}", callback_data=f"team:{t['id']}")
    b.button(text=texts.RANDOM_TEAM, callback_data="team:random")
    b.adjust(1)
    return b.as_markup()


def main_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное reply-меню. Мой прогресс/Лидерборд открывают Mini App, если задан URL."""
    def wa(text: str) -> KeyboardButton:
        if config.webapp_url:
            return KeyboardButton(text=text, web_app=WebAppInfo(url=config.webapp_url))
        return KeyboardButton(text=text)

    rows = [
        [KeyboardButton(text=texts.STEPS_BUTTON)],
        [wa(texts.MENU_PROGRESS), wa(texts.MENU_BOARD)],
        [KeyboardButton(text=texts.MENU_RULES), KeyboardButton(text=texts.MENU_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=texts.MENU_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_panel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏆 Лидерборд", callback_data="adm:board")
    b.button(text="📣 Рассылка", callback_data="adm:broadcast")
    b.button(text="🔎 На проверку", callback_data="adm:review")
    b.button(text="📊 Вовлечённость", callback_data="adm:stats")
    b.adjust(2)
    return b.as_markup()


def confirm_steps_kb(steps: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Верно ✅", callback_data=f"steps_ok:{steps}"),
        InlineKeyboardButton(text="Исправить", callback_data="steps_fix"),
    ]])
