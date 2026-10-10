"""Админ-режим P&C: /admin панель, подтверждение регистраций, /leaderboard,
/stats, /dq, /emojiid. Модерация результатов и настройки — в admin_settings."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape, unescape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import db, keyboards, notify, settings, texts
from bot.config import config
from bot.premium_emoji import pe

router = Router()


def _is_admin(tg_id: int) -> bool:
    return settings.is_admin(tg_id)


def _is_owner(tg_id: int) -> bool:
    """Владелец = админ из env ADMIN_IDS или назначенный владельцем в
    «👑 Админы». Только владельцу доступен сброс марафона и управление
    владельцами: обычные админы стереть всю базу не могут."""
    return settings.is_owner(tg_id)


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(texts.ADMIN_PANEL,
                         reply_markup=keyboards.admin_panel_kb(_is_owner(message.from_user.id)))


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
    await cb.message.edit_text(
        texts.ADMIN_PANEL,
        reply_markup=keyboards.admin_panel_kb(_is_owner(cb.from_user.id)))
    await cb.answer()


# ---- Сброс марафона: полный перезапуск с нуля ------------------------------

class Wipe(StatesGroup):
    confirm = State()


WIPE_WORD = "СБРОС"


@router.callback_query(F.data == "adm:wipe")
async def wipe_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(cb.from_user.id):
        return await cb.answer("Сброс доступен только владельцу бота.",
                               show_alert=True)
    s = await db.marathon_stats()
    await state.set_state(Wipe.confirm)
    await cb.message.answer(
        "🧨 <b>Полный сброс марафона</b>\n\n"
        "<b>Будет удалено безвозвратно:</b>\n"
        f"• участники — <b>{s['participants']}</b>\n"
        f"• результаты по дням — <b>{s['entries']}</b>\n"
        f"• недельные отчёты и бонусы — <b>{s['weekly']}</b>\n"
        f"• челленджи — <b>{s['challenges']}</b>, флешмобы — <b>{s['flashmobs']}</b>\n"
        "• серии, командные очки, история рассылок\n\n"
        f"<b>Останется:</b> команды ({s['teams']}), настройки, каналы, "
        "список админов, оформление.\n\n"
        f"Участникам придётся зарегистрироваться заново через /start.\n\n"
        f"Если уверены — пришлите слово <code>{WIPE_WORD}</code> "
        "(ровно так, заглавными). Любой другой текст отменит сброс, "
        "как и /cancel.")
    await cb.answer()


@router.message(Wipe.confirm, F.text)
async def wipe_do(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not _is_owner(message.from_user.id):
        return
    if message.text.strip() != WIPE_WORD:
        await message.answer("Сброс отменён — слово не совпало. Ничего не удалено.")
        return
    s = await db.wipe_marathon()
    await settings.load()   # сброшены и отметки картинок дня
    await message.answer(
        "🧨 <b>Марафон сброшен</b>\n\n"
        f"Удалено: участников <b>{s['participants']}</b>, результатов "
        f"<b>{s['entries']}</b>, недельных отчётов <b>{s['weekly']}</b>, "
        f"челленджей <b>{s['challenges']}</b>, флешмобов <b>{s['flashmobs']}</b>.\n"
        f"Команды на месте: <b>{s['teams']}</b>.\n\n"
        f"📅 Даты нового марафона: <b>{texts.marathon_dates()}</b>, "
        f"таймзона <b>{config.tz_name}</b>.\n"
        "Можно запускать: участники нажимают /start и регистрируются заново.")


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
    await cb.message.answer(texts.render_leaderboard(teams, top))
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


@router.message(Command("health"))
async def health(message: Message) -> None:
    """Живая самодиагностика: что за конфигурация реально работает.
    Нужна, когда «бот молчит» — если ответ пришёл, процесс жив, и видно,
    с какой таймзоной, датами и настройками он поднялся."""
    if not _is_admin(message.from_user.id):
        return
    now = datetime.now(config.tz)
    today = now.date()
    phase = ("идёт" if config.marathon_start <= today <= config.marathon_end
             else "ещё не начался" if today < config.marathon_start else "завершён")
    from bot.handlers.steps import DEADLINE, _day_closed
    s = await db.marathon_stats()
    join = settings.channel_id("join")
    review = settings.channel_id("review")
    teams = await db.teams_with_capacity()
    fill = " · ".join(
        f"{escape(t['name'])} {t['taken']}/{t['capacity']}"
        + (" ⚠️" if t["taken"] > t["capacity"] else "") for t in teams) or "—"
    await message.answer(
        "🩺 <b>Состояние бота</b>\n\n"
        f"🕒 Сейчас: <b>{now.strftime('%d.%m.%Y %H:%M')}</b> "
        f"(<code>{config.tz_name}</code>)\n"
        f"📅 Марафон: <b>{config.marathon_start.strftime('%d.%m')}–"
        f"{config.marathon_end.strftime('%d.%m.%Y')}</b> — {phase}\n"
        f"⏰ Приём шагов сегодня: <b>"
        + ("закрыт до старта" if phase == "ещё не начался" else
           "закрыт — марафон завершён" if phase == "завершён" else
           "закрыт (после дедлайна)" if _day_closed() else
           f"открыт до {DEADLINE[0]}:{DEADLINE[1]:02d}")
        + "</b>\n\n"
        f"👥 Участников: <b>{s['participants']}</b> · результатов: "
        f"<b>{s['entries']}</b> · команд: <b>{s['teams']}</b>\n"
        f"🌳 Состав команд: {fill}\n"
        f"🎲 Челленджей: <b>{s['challenges']}</b> · флешмобов: <b>{s['flashmobs']}</b>\n"
        f"👑 Админов: <b>{len(settings.admin_ids())}</b>\n"
        f"📢 Канал заявок: <b>{join or 'не задан'}</b> · проверки: "
        f"<b>{review or 'не задан'}</b>\n"
        f"🔗 Mini App: <b>{settings.webapp_url() or 'не задан'}</b>")


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


# ---- 👑 Админы: управление прямо из админ-панели ---------------------------
# Без Render: человек нажимает /start в боте, админ находит его поиском по
# ФИО / @username / ID и назначает. Владельцы из env ADMIN_IDS неснимаемы.

class AdminMgmt(StatesGroup):
    search = State()


def _who(tid: int, r) -> str:
    if r is not None and (r["full_name"] or "").strip():
        name = escape(r["full_name"])
        return name + (f" (@{escape(r['username'])})" if r["username"] else "")
    if r is not None and r["username"]:
        return "@" + escape(r["username"])
    return f"ID {tid}"


async def _admins_view(viewer: int):
    ids = sorted(settings.admin_ids())
    people = await db.people_by_ids(ids)
    owners = settings.owner_ids()
    lines = ["👑 <b>Администраторы</b>\n"]
    b = InlineKeyboardBuilder()
    for tid in ids:
        role = "👑 владелец" if tid in owners else "🛡 админ"
        fixed = " · <i>из настроек сервера</i>" if tid in config.admin_ids else ""
        lines.append(f"• {_who(tid, people.get(tid))} — {role}{fixed}")
        if tid not in config.admin_ids:
            b.button(text=f"{'👑' if tid in owners else '🛡'} "
                          f"{unescape(_who(tid, people.get(tid)).split(' (@')[0])[:28]}",
                     callback_data=f"adm:ad:{tid}")
    lines.append(
        "\n<b>Как добавить:</b> человек нажимает /start в боте, затем «➕ Добавить "
        "админа» и поиск по ФИО, @username или Telegram ID.\n"
        "🛡 <b>Админ</b> — модерация, ручной ввод, рассылки, отчёты.\n"
        "👑 <b>Владелец</b> — всё то же + сброс марафона и назначение владельцев.")
    b.button(text="➕ Добавить админа", callback_data="adm:adadd")
    b.button(text="⬅️ Назад", callback_data="adm:back")
    b.adjust(1)
    return "\n".join(lines), b.as_markup()


@router.callback_query(F.data == "adm:admins")
async def admins_list(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.clear()
    text, kb = await _admins_view(cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:adadd")
async def admins_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(AdminMgmt.search)
    await cb.message.answer(
        "🔎 Напишите <b>часть ФИО</b>, <b>@username</b> или <b>Telegram ID</b> "
        "будущего админа.\n\nВажно: он должен хотя бы раз нажать /start в боте. "
        "/cancel — отмена.")
    await cb.answer()


@router.message(AdminMgmt.search, F.text)
async def admins_search(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    q = message.text.strip()
    rows = await db.find_participants(q, limit=10, with_unregistered=True) if q else []
    if not rows:
        return await message.answer(
            "Никого не нашёл 🤷 Проверьте, что человек нажал /start в боте, и "
            "пришлите другой запрос. /cancel — отмена.")
    await state.clear()
    admins = settings.admin_ids()
    b = InlineKeyboardBuilder()
    for r in rows:
        mark = "✅ " if r["telegram_id"] in admins else ""
        b.button(text=unescape(mark + _who(r["telegram_id"], r))[:60],
                 callback_data=f"adm:adpick:{r['telegram_id']}")
    b.button(text="⬅️ К списку админов", callback_data="adm:admins")
    b.adjust(1)
    await message.answer("Кого назначить администратором? (✅ — уже админ)",
                         reply_markup=b.as_markup())


async def _admin_card(cb: CallbackQuery, tid: int) -> None:
    people = await db.people_by_ids([tid])
    who = _who(tid, people.get(tid))
    viewer_owner = _is_owner(cb.from_user.id)
    b = InlineKeyboardBuilder()
    if not settings.is_admin(tid):
        text = f"👤 {who}\n\nСейчас не администратор."
        b.button(text="🛡 Сделать админом", callback_data=f"adm:adset:{tid}:a")
        if viewer_owner:
            b.button(text="👑 Сделать владельцем", callback_data=f"adm:adset:{tid}:o")
    elif tid in config.admin_ids:
        text = (f"👤 {who}\n\n👑 Владелец из настроек сервера (ADMIN_IDS) — "
                "его права меняются только там.")
    else:
        owner = settings.is_owner(tid)
        text = f"👤 {who}\n\nРоль: {'👑 владелец' if owner else '🛡 админ'}."
        if viewer_owner:
            if owner:
                b.button(text="🛡 Оставить только админом", callback_data=f"adm:adset:{tid}:a")
            else:
                b.button(text="👑 Сделать владельцем", callback_data=f"adm:adset:{tid}:o")
        if tid != cb.from_user.id and (viewer_owner or not owner):
            b.button(text="🚫 Снять с админов", callback_data=f"adm:adset:{tid}:x")
    b.button(text="⬅️ К списку админов", callback_data="adm:admins")
    b.adjust(1)
    await cb.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adm:adpick:") | F.data.startswith("adm:ad:"))
async def admins_card(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await _admin_card(cb, int(cb.data.rsplit(":", 1)[1]))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:adset:"))
async def admins_set(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    _, _, tid_s, action = cb.data.split(":")
    tid = int(tid_s)
    viewer_owner = _is_owner(cb.from_user.id)
    if tid in config.admin_ids:
        return await cb.answer("Этот владелец задан в настройках сервера.", show_alert=True)
    # Владельцами распоряжаются только владельцы; себя снять нельзя — чтобы
    # случайно не остаться без доступа.
    if (action == "o" or settings.is_owner(tid)) and not viewer_owner:
        return await cb.answer("Это может сделать только владелец.", show_alert=True)
    if action == "x" and tid == cb.from_user.id:
        return await cb.answer("Себя снять нельзя — попросите другого админа.",
                               show_alert=True)
    was_admin = settings.is_admin(tid)
    from bot import commands
    if action == "x":
        await settings.remove_admin(tid)
        await db.set_role(tid, "participant")
        await commands.apply_for(cb.bot, tid)
        await cb.answer("Снят с админов")
        await notify.broadcast(cb.bot, [tid], "ℹ️ Вы больше не администратор марафона.")
    else:
        if action == "o":
            await settings.add_owner(tid)
        else:
            await settings.add_admin(tid)
            await settings.remove_owner(tid)
        await db.set_role(tid, "admin")
        await commands.apply_for(cb.bot, tid)
        await cb.answer("Готово")
        if not was_admin:
            await notify.broadcast(cb.bot, [tid], (
                "👑 Вас назначили администратором марафона Step Together.\n"
                "Админ-панель — команда /admin."))
    text, kb = await _admins_view(cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=kb)


# ---- 🖼 Картинки дня: расписание и превью ----------------------------------

@router.callback_query(F.data == "adm:daily")
async def daily_list(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    from bot import daily
    today = datetime.now(config.tz).date()
    lines = ["🖼 <b>Картинки дня</b> — уходят всем участникам в 09:00\n"]
    b = InlineKeyboardBuilder()
    for n, (_, title, _) in daily.SLIDES.items():
        d = daily.day_of(n)
        info = daily.sent_info(n)
        if not daily.path(n).exists():
            st = "⚠️ нет файла"
        elif info:
            st = f"✅ отправлено ({info.split(':')[1]} чел.)"
        elif d < today:
            st = "— пропущено"
        elif d == today:
            st = "⏳ сегодня в 09:00"
        else:
            st = "🕒 запланировано"
        lines.append(f"<b>{n:02d}</b> · {d.strftime('%d.%m')} · {escape(title)} — {st}")
        if daily.path(n).exists():
            b.button(text=f"👁 {n:02d}", callback_data=f"adm:dprev:{n}")
    lines.append("\n👁 — превью себе в личку.")
    b.adjust(6)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back"))
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:dprev:"))
async def daily_preview(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    from bot import daily
    ok = await daily.send_preview(cb.bot, cb.from_user.id, int(cb.data.rsplit(":", 1)[1]))
    await cb.answer("Отправил превью в личку" if ok else "Не получилось отправить",
                    show_alert=not ok)


@router.callback_query(F.data == "adm:brandmenu")
async def brand_menu(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    from bot import brand
    from bot.menu import send_main_menu
    await brand.use_default_menu()
    await cb.answer("Готово — так теперь выглядит главное меню")
    await send_main_menu(cb.bot, cb.from_user.id, "🪴 Фирменная картинка WE GROW установлена.")


@router.callback_query(F.data == "adm:brandava")
async def brand_avatar(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    from bot import brand
    ok = await brand.set_avatar(cb.bot)
    await cb.answer("Аватар бота обновлён ✅" if ok else
                    "Telegram не принял аватар — можно поставить через @BotFather → /setuserpic",
                    show_alert=True)


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
    # Меню команд ставим сразу — иначе новый админ не увидит /admin у себя.
    from bot import commands
    ok = await commands.apply_for(message.bot, tid)
    hint = ("Админ-команды уже в его меню." if ok else
            "Ему нужно открыть чат с ботом и нажать /start — тогда админ-команды "
            "появятся в меню.")
    await message.answer(
        f"✅ Пользователь <code>{tid}</code> теперь администратор.\n" + hint + "\n"
        "Ему доступны /admin и все уведомления P&amp;C наравне с остальными админами.")


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
    if settings.is_owner(tid) and not _is_owner(message.from_user.id):
        await message.answer("Владельца может снять только владелец.")
        return
    await settings.remove_admin(tid)
    await db.set_role(tid, "participant")
    from bot import commands
    await commands.apply_for(message.bot, tid)   # вернуть обычное меню команд
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
    await message.answer(texts.render_leaderboard(teams, top))
