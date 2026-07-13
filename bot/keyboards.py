"""Клавиатуры."""
from __future__ import annotations

import asyncpg
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts


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


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.STEPS_BUTTON)]],
        resize_keyboard=True,
    )


def confirm_steps_kb(steps: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Верно ✅", callback_data=f"steps_ok:{steps}"),
        InlineKeyboardButton(text="Исправить", callback_data="steps_fix"),
    ]])
