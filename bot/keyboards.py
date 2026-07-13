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

from bot import premium_emoji, settings, texts
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


def _mbtn(name: str) -> KeyboardButton:
    """Кнопка меню: подпись из настроек + премиум-иконка (Bot API 9.4),
    если премиум включён и иконка задана (иначе Telegram отклонит)."""
    icon = settings.icon(name) if premium_emoji.ENABLED else None
    return KeyboardButton(text=settings.label(name), icon_custom_emoji_id=icon)


def main_kb() -> ReplyKeyboardMarkup:
    """Главное reply-меню участника. Подписи и иконки кнопок — из настроек
    (меняются через /admin). Админ-функции — по команде /admin."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [_mbtn("steps")],
            [_mbtn("progress"), _mbtn("board")],
            [_mbtn("rules"), _mbtn("help")],
        ],
        resize_keyboard=True,
    )


def open_app_kb(text: str = "🌱 Открыть приложение") -> InlineKeyboardMarkup | None:
    """Inline-кнопка, открывающая Mini App с корректным initData."""
    if not config.webapp_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=config.webapp_url))
    ]])


def approve_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"appr:{tg_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej:{tg_id}"),
    ]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏆 Лидерборд", callback_data="adm:board")
    b.button(text="📊 Вовлечённость", callback_data="adm:stats")
    b.button(text="🔎 На проверку", callback_data="adm:review")
    b.button(text="📣 Рассылка", callback_data="adm:broadcast")
    b.button(text="🖼 Медиа меню", callback_data="adm:media")
    b.button(text="🔀 Перевод в команду", callback_data="adm:move")
    b.button(text="✏️ Кнопки меню", callback_data="adm:labels")
    b.button(text="🎨 Иконки кнопок", callback_data="adm:icons")
    b.adjust(2)
    return b.as_markup()


def bc_builder_kb(draft: dict) -> InlineKeyboardMarkup:
    """Клавиатура билдера рассылки. draft: {text, media, buttons}."""
    b = InlineKeyboardBuilder()
    media = "🖼 Медиа ✅" if draft.get("media") else "🖼 Добавить медиа"
    nbtn = len(draft.get("buttons", []))
    b.button(text=media, callback_data="bc:media")
    b.button(text=f"🔘 Кнопки ({nbtn})", callback_data="bc:buttons")
    b.button(text="👁 Предпросмотр", callback_data="bc:preview")
    b.button(text="🚀 Отправить всем", callback_data="bc:send")
    b.button(text="✖️ Отмена", callback_data="bc:cancel")
    b.adjust(2, 1, 1, 1)
    return b.as_markup()


def bc_buttons_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Своя кнопка (текст + ссылка)", callback_data="bc:btn_custom")
    if config.webapp_url:
        b.button(text="📊 Кнопка «Открыть приложение»", callback_data="bc:btn_app")
    b.button(text="🗑 Очистить кнопки", callback_data="bc:btn_clear")
    b.button(text="⬅️ Назад", callback_data="bc:back")
    b.adjust(1)
    return b.as_markup()


def teams_pick_kb(teams: list[asyncpg.Record], prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in teams:
        b.button(text=f"{t['name']} — {t['taken']}/{t['capacity']}", callback_data=f"{prefix}:{t['id']}")
    b.adjust(1)
    return b.as_markup()


def labels_pick_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for name, cur in settings.all_labels().items():
        b.button(text=cur, callback_data=f"lbl:{name}")
    b.button(text="↩️ Сбросить к стандартным", callback_data="lbl:reset")
    b.adjust(1)
    return b.as_markup()


def icons_pick_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for name in settings.DEFAULT_LABELS:
        mark = "🎨" if settings.icon(name) else "▫️"
        b.button(text=f"{mark} {settings.label(name)}", callback_data=f"ico:{name}")
    b.button(text="↩️ Убрать все иконки", callback_data="ico:reset")
    b.adjust(1)
    return b.as_markup()


def open_app_inline(text: str) -> InlineKeyboardButton | None:
    if not config.webapp_url:
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=config.webapp_url))


def confirm_steps_kb(steps: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Верно ✅", callback_data=f"steps_ok:{steps}"),
        InlineKeyboardButton(text="Исправить", callback_data="steps_fix"),
    ]])
