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
    если премиум включён и иконка задана. Прогресс/Лидерборд открывают
    Mini App напрямую (web_app)."""
    icon = settings.icon(name) if premium_emoji.ENABLED else None
    web_app = None
    if name in ("progress", "board") and config.webapp_url:
        web_app = WebAppInfo(url=config.webapp_url)
    return KeyboardButton(text=settings.label(name), icon_custom_emoji_id=icon, web_app=web_app)


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
    b.button(text="👥 Пользователи", callback_data="adm:users")
    b.adjust(2)
    return b.as_markup()


def _status_mark(r) -> str:
    if r["disqualified_at"]:
        return "⛔"
    return "✅" if r["approved_at"] else "⏳"


def users_page_kb(rows, offset: int, total: int, pending: int, page_size: int = 8) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rows:
        b.button(text=f"{_status_mark(r)} {r['full_name']} · {r['team_name'] or '—'}",
                 callback_data=f"usr:{r['telegram_id']}")
    b.adjust(1)
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"usrpg:{max(0, offset - page_size)}"))
    if offset + page_size < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"usrpg:{offset + page_size}"))
    if nav:
        b.row(*nav)
    if pending:
        b.row(InlineKeyboardButton(text=f"⏳ Заявки на подтверждение ({pending})",
                                   callback_data="adm:pending"))
    return b.as_markup()


def user_card_kb(p) -> InlineKeyboardMarkup:
    tg = p["telegram_id"]
    b = InlineKeyboardBuilder()
    if p["disqualified_at"]:
        b.button(text="♻️ Восстановить", callback_data=f"usrun:{tg}")
    else:
        if not p["approved_at"]:
            b.button(text="✅ Подтвердить", callback_data=f"appr:{tg}")
            b.button(text="❌ Отклонить", callback_data=f"rej:{tg}")
        b.button(text="⛔ Дисквалифицировать", callback_data=f"usrdq:{tg}")
    b.button(text="🔀 Перевести в команду", callback_data=f"usrmv:{tg}")
    b.button(text="🗑 Удалить", callback_data=f"usrdel:{tg}")
    b.button(text="⬅️ К списку", callback_data="usrpg:0")
    b.adjust(2, 1, 1, 1)
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
