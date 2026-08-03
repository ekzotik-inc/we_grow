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


def phone_kb() -> ReplyKeyboardMarkup:
    """Кнопка «Поделиться телефоном» (request_contact)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.SHARE_PHONE_BUTTON, request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


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
    url = settings.webapp_url()
    if name in ("progress", "board") and url:
        web_app = WebAppInfo(url=url)
    return KeyboardButton(text=settings.label(name), icon_custom_emoji_id=icon, web_app=web_app)


def main_kb() -> ReplyKeyboardMarkup:
    """Главное reply-меню участника. Подписи и иконки кнопок — из настроек
    (меняются через /admin). Админ-функции — по команде /admin."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [_mbtn("steps")],
            [_mbtn("weekly")],
            [_mbtn("progress"), _mbtn("board")],
            [_mbtn("rules"), _mbtn("help")],
            [_mbtn("feedback")],
        ],
        resize_keyboard=True,
    )


def feedback_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💬 Написать сотруднику P&C", url=config.feedback_url)
    ]])


def open_app_kb(text: str = "🌱 Открыть приложение") -> InlineKeyboardMarkup | None:
    """Inline-кнопка, открывающая Mini App с корректным initData."""
    url = settings.webapp_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
    ]])


def approve_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"appr:{tg_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej:{tg_id}"),
    ]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    """Главная админ-панель — сгруппирована, оформление вынесено в подменю."""
    b = InlineKeyboardBuilder()
    b.button(text="🧾 Результаты", callback_data="adm:subs")
    b.button(text="✍️ Ручной ввод", callback_data="adm:manual")
    b.button(text="🗑 Отмена результата", callback_data="adm:undo")
    b.button(text="🎲 Тайный челлендж", callback_data="adm:chal")
    b.button(text="🤝 Командный флешмоб", callback_data="adm:flash")
    b.button(text="📊 Активности и участие", callback_data="adm:acts")
    b.button(text="👥 Участники", callback_data="adm:users")
    b.button(text="🌳 Команды", callback_data="adm:teams")
    b.button(text="🏆 Лидерборд", callback_data="adm:board")
    b.button(text="📊 Вовлечённость", callback_data="adm:stats")
    b.button(text="📣 Рассылка", callback_data="adm:broadcast")
    b.button(text="📥 Экспорт в Excel", callback_data="adm:export")
    b.button(text="📢 Каналы", callback_data="adm:channels")
    b.button(text="⚙️ Оформление", callback_data="adm:design")
    b.adjust(2)
    return b.as_markup()


def teams_admin_kb(teams: list[asyncpg.Record]) -> InlineKeyboardMarkup:
    """Список команд для управления: у каждой — занятость, снизу «добавить»."""
    b = InlineKeyboardBuilder()
    for t in teams:
        b.button(text=f"🌳 {t['name']} — {t['taken']}/{t['capacity']}",
                 callback_data=f"tm:{t['id']}")
    b.button(text="➕ Добавить команду", callback_data="tm:add")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(1)
    return b.as_markup()


def team_card_kb(team_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Переименовать", callback_data=f"tmren:{team_id}")
    b.button(text="🔢 Вместимость", callback_data=f"tmcap:{team_id}")
    b.button(text="🗑 Удалить", callback_data=f"tmdel:{team_id}")
    b.button(text="⬅️ К списку команд", callback_data="adm:teams")
    b.adjust(2, 1, 1)
    return b.as_markup()


def channels_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📥 Канал заявок на вступление", callback_data="ch:join")
    b.button(text="🧾 Канал проверки результатов", callback_data="ch:review")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(1)
    return b.as_markup()


def design_panel_kb() -> InlineKeyboardMarkup:
    """Подменю «Оформление»: медиа, подписи и иконки кнопок."""
    b = InlineKeyboardBuilder()
    b.button(text="🖼 Медиа меню", callback_data="adm:media")
    b.button(text="✏️ Кнопки меню", callback_data="adm:labels")
    b.button(text="🎨 Иконки кнопок", callback_data="adm:icons")
    b.button(text="🔗 Ссылка приложения", callback_data="adm:appurl")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(1)
    return b.as_markup()


def moderate_kb(entry_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"mod_ok:{entry_id}")
    b.button(text="❌ Отклонить", callback_data=f"mod_no:{entry_id}")
    b.button(text="⚠️ Предупреждение", callback_data=f"mod_warn:{entry_id}")
    b.adjust(2, 1)
    return b.as_markup()


_ENTRY_MARKS = {"accepted": "✅", "pending": "⏳", "rejected": "❌"}


def manual_days_kb(tg_id: int, days: list[tuple]) -> InlineKeyboardMarkup:
    """Дни марафона для ручного ввода: days — [(date, status|None)].
    День с уже существующим результатом кликается, но только чтобы показать
    подсказку — зачесть поверх него нельзя."""
    b = InlineKeyboardBuilder()
    for day, status in days:
        label = day.strftime("%d.%m")
        if status is None:
            b.button(text=label, callback_data=f"mand:{tg_id}:{day.isoformat()}")
        else:
            b.button(text=f"{_ENTRY_MARKS.get(status, '•')}{label}",
                     callback_data=f"manbusy:{status}")
    b.adjust(4)
    b.row(InlineKeyboardButton(text="🔍 Другой участник", callback_data="adm:manual"))
    return b.as_markup()


def manual_confirm_kb(tg_id: int, day, steps: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Зачислить",
                             callback_data=f"manok:{tg_id}:{day.isoformat()}:{steps}"),
        InlineKeyboardButton(text="✖️ Отмена", callback_data="man:cancel"),
    ]])


def results_days_kb(tg_id: int, days: list[tuple]) -> InlineKeyboardMarkup:
    """Календарь результатов участника для админа: days — [(date, entry|None)].
    День с записью открывает карточку, пустой — только подсказку."""
    b = InlineKeyboardBuilder()
    for day, e in days:
        label = day.strftime("%d.%m")
        if e is None:
            b.button(text=f"·{label}", callback_data="resnone")
        else:
            b.button(text=f"{_ENTRY_MARKS.get(e['status'], '•')}{label}",
                     callback_data=f"resd:{e['id']}")
    b.adjust(4)
    b.row(InlineKeyboardButton(text="🔍 Другой участник", callback_data="adm:undo"))
    return b.as_markup()


def result_card_kb(e) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    # Вернуть на проверку есть смысл только тому, у кого есть скриншот:
    # запись снова попадёт в очередь модерации.
    if e["screenshot_file_id"] and e["status"] != "pending":
        b.button(text="↩️ Вернуть на проверку", callback_data=f"resrep:{e['id']}")
    b.button(text="🗑 Отменить результат", callback_data=f"resdel:{e['id']}")
    b.button(text="⬅️ К календарю", callback_data=f"res:{e['participant_id']}")
    b.adjust(1)
    return b.as_markup()


def result_delete_confirm_kb(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, отменить", callback_data=f"resdelok:{entry_id}"),
        InlineKeyboardButton(text="Назад", callback_data=f"resd:{entry_id}"),
    ]])


# ---- «Тайный челлендж» -----------------------------------------------------

def challenge_card_kb(announced: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=("📣 Отправить пуш ещё раз" if announced
                   else "🚀 Запустить: оповестить участников"),
             callback_data="chann")
    b.button(text="✏️ Пересоздать", callback_data="chnew")
    b.button(text="🗑 Удалить челлендж", callback_data="chdel")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(1)
    return b.as_markup()


def challenge_mult_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="×2", callback_data="chmul:2")
    b.button(text="×3", callback_data="chmul:3")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(2, 1)
    return b.as_markup()


def challenge_time_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌞 Весь день", callback_data="chtime:all")
    for hh in (18, 19, 20):
        b.button(text=f"⏰ После {hh}:00", callback_data=f"chtime:{hh}")
    b.button(text="⬅️ Назад", callback_data="adm:chal")
    b.adjust(1, 3, 1)
    return b.as_markup()


def challenge_teams_kb(teams: list[asyncpg.Record], picked: set) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in teams:
        mark = "✅" if t["id"] in picked else "▫️"
        b.button(text=f"{mark} {t['name']}", callback_data=f"chteam:{t['id']}")
    b.adjust(1)
    all_on = len(picked) == len(teams)
    b.row(InlineKeyboardButton(text="◻️ Снять все" if all_on else "🌳 Все команды",
                               callback_data="chteam:all"))
    b.row(InlineKeyboardButton(text="Далее ➡️", callback_data="chteams:done"))
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:chal"))
    return b.as_markup()


def challenge_confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👁 Предпросмотр пуша", callback_data="chprev")
    b.button(text="🚀 Запустить и оповестить", callback_data="chsave:1")
    b.button(text="🤫 Подготовить без пуша", callback_data="chsave:0")
    b.button(text="✖️ Отмена", callback_data="adm:back")
    b.adjust(1)
    return b.as_markup()


# ---- «Командный флешмоб» ---------------------------------------------------

def _pick_kb(options: list[tuple[str, str]], back: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, data in options:
        b.button(text=text, callback_data=data)
    b.adjust(3)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back))
    return b.as_markup()


def flashmob_pct_kb() -> InlineKeyboardMarkup:
    return _pick_kb([(f"{p}%", f"fmpct:{p}") for p in (60, 70, 80, 100)], "adm:back")


def flashmob_steps_kb() -> InlineKeyboardMarkup:
    return _pick_kb([(f"{s}", f"fmsteps:{s}") for s in (5000, 8000, 10000)], "adm:flash")


def flashmob_bonus_kb() -> InlineKeyboardMarkup:
    return _pick_kb([(f"+{p}", f"fmbonus:{p}") for p in (10, 20, 30, 50)], "adm:flash")


def flashmob_teams_kb(teams: list[asyncpg.Record], picked: set) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in teams:
        mark = "✅" if t["id"] in picked else "▫️"
        b.button(text=f"{mark} {t['name']}", callback_data=f"fmteam:{t['id']}")
    b.adjust(1)
    all_on = len(picked) == len(teams)
    b.row(InlineKeyboardButton(text="◻️ Снять все" if all_on else "🌳 Все команды",
                               callback_data="fmteam:all"))
    b.row(InlineKeyboardButton(text="Далее ➡️", callback_data="fmteams:done"))
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:flash"))
    return b.as_markup()


def flashmob_confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👁 Предпросмотр пуша", callback_data="fmprev")
    b.button(text="🚀 Запустить и оповестить", callback_data="fmsave:1")
    b.button(text="🤫 Подготовить без пуша", callback_data="fmsave:0")
    b.button(text="✖️ Отмена", callback_data="adm:back")
    b.adjust(1)
    return b.as_markup()


def flashmob_card_kb(announced: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="♻️ Обновить прогресс", callback_data="adm:flash")
    b.button(text=("📣 Отправить пуш ещё раз" if announced
                   else "🚀 Запустить: оповестить участников"),
             callback_data="fmann")
    b.button(text="✏️ Пересоздать", callback_data="fmnew")
    b.button(text="🗑 Удалить флешмоб", callback_data="fmdel")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(1)
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
    b.button(text="🧹 Очистить результаты", callback_data=f"usrclr:{tg}")
    b.button(text="🗑 Удалить", callback_data=f"usrdel:{tg}")
    b.button(text="⬅️ К списку", callback_data="usrpg:0")
    b.adjust(2, 1, 1, 1, 1)
    return b.as_markup()


def clear_results_confirm_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🧹 Да, очистить", callback_data=f"usrclryes:{tg_id}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"usr:{tg_id}"),
    ]])


def bc_builder_kb(draft: dict) -> InlineKeyboardMarkup:
    """Клавиатура билдера рассылки. draft: {text, media, buttons}."""
    b = InlineKeyboardBuilder()
    media = "🖼 Медиа ✅" if draft.get("media") else "🖼 Добавить медиа"
    nbtn = len(draft.get("buttons", []))
    b.button(text=media, callback_data="bc:media")
    b.button(text=f"🔘 Кнопки ({nbtn})", callback_data="bc:buttons")
    b.button(text="👁 Предпросмотр", callback_data="bc:preview")
    b.button(text="🚀 Отправить всем", callback_data="bc:send")
    b.button(text="⏰ Отложить отправку", callback_data="bc:later")
    b.button(text="✖️ Отмена", callback_data="bc:cancel")
    b.adjust(2, 1, 1, 1, 1)
    return b.as_markup()


def bc_buttons_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Своя кнопка (текст + ссылка)", callback_data="bc:btn_custom")
    if settings.webapp_url():
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
    url = settings.webapp_url()
    if not url:
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
