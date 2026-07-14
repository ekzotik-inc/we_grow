"""Админ-настройки: медиа меню, перевод в команду, переименование кнопок,
многошаговый билдер рассылки (текст + медиа + кнопки + премиум-эмодзи)."""
from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from backend.scoring import points_for_steps
from bot import db, keyboards, notify, premium_emoji, settings, textfmt, texts
from bot.config import config

router = Router()


def _is_admin(tg_id: int) -> bool:
    return tg_id in config.admin_ids


class Media(StatesGroup):
    waiting = State()


class Move(StatesGroup):
    query = State()


class Labels(StatesGroup):
    waiting = State()


class Icons(StatesGroup):
    waiting = State()


class BC(StatesGroup):
    text = State()
    wait_media = State()
    wait_button = State()


# ---- Медиа главного меню --------------------------------------------------

@router.callback_query(F.data == "adm:media")
async def media_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(Media.waiting)
    await cb.message.answer("🖼 Пришли <b>фото</b>, <b>гиф</b> или <b>видео</b> — оно станет "
                            "шапкой главного меню у всех.\n/cancel — отмена, "
                            "«-» — убрать медиа.")
    await cb.answer()


@router.message(Media.waiting, F.text == "-")
async def media_clear(message: Message, state: FSMContext) -> None:
    await state.clear()
    await settings.set("menu_media", None)
    await message.answer("Медиа меню убрано ✅")


@router.message(Media.waiting, F.photo | F.animation | F.video)
async def media_save(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.photo:
        await settings.set_menu_media("photo", message.photo[-1].file_id)
    elif message.animation:
        await settings.set_menu_media("animation", message.animation.file_id)
    else:
        await settings.set_menu_media("video", message.video.file_id)
    await message.answer("Медиа главного меню обновлено ✅ Оно появится при /start.")


# ---- Перевод участника в другую команду -----------------------------------

@router.message(Command("move"))
async def move_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(Move.query)
    await message.answer("🔀 Кого перевести? Пришли <b>ID</b> или часть <b>ФИО</b>.")


@router.message(Move.query, F.text)
async def move_search(message: Message, state: FSMContext) -> None:
    rows = await db.find_participants(message.text.strip())
    if not rows:
        await message.answer("Никого не нашёл. Попробуй ещё раз или /cancel.")
        return
    b = keyboards.InlineKeyboardBuilder()
    for r in rows:
        team = r["team_name"] or "—"
        b.button(text=f"{r['full_name']} ({team})", callback_data=f"mvp:{r['telegram_id']}")
    b.adjust(1)
    await state.clear()
    await message.answer("Выбери участника:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("mvp:"))
async def move_pick_person(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    target = int(cb.data.split(":")[1])
    await state.update_data(move_target=target)
    teams = await db.teams_with_capacity()
    await cb.message.edit_text("В какую команду перевести?",
                               reply_markup=keyboards.teams_pick_kb(teams, "mvt"))
    await cb.answer()


@router.callback_query(F.data.startswith("mvt:"))
async def move_do(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    team_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    target = data.get("move_target")
    await state.clear()
    if not target:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    await db.move_to_team(target, team_id)
    p = await db.get_participant(target)
    tname = next((t["name"] for t in await db.teams_with_capacity() if t["id"] == team_id), "?")
    await cb.message.edit_text(f"✅ {escape(p['full_name'])} переведён(а) в команду <b>{escape(tname)}</b>.")
    try:
        await cb.bot.send_message(target, texts.moved_note(escape(tname)))
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Готово ✅")


# ---- Переименование кнопок меню -------------------------------------------

@router.callback_query(F.data == "adm:labels")
async def labels_start(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await cb.message.answer("✏️ Какую кнопку переименовать? (обычные эмодзи поддерживаются, "
                            "премиум-эмодзи в кнопках Telegram не показывает)",
                            reply_markup=keyboards.labels_pick_kb())
    await cb.answer()


@router.callback_query(F.data == "lbl:reset")
async def labels_reset(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    for name in settings.DEFAULT_LABELS:
        await settings.set(f"label_{name}", None)
    await cb.message.edit_text("Кнопки сброшены к стандартным ✅ (обновятся при /start)")
    await cb.answer()


@router.callback_query(F.data.startswith("lbl:"))
async def labels_pick(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    name = cb.data.split(":")[1]
    if name not in settings.DEFAULT_LABELS:
        return await cb.answer()
    await state.set_state(Labels.waiting)
    await state.update_data(label_name=name)
    await cb.message.answer(
        f"Текущее название: «{settings.label(name)}»\n\n"
        "Пришли <b>новое название</b> — оно полностью заменит старое.\n"
        "Хочешь оставить только премиум-иконку — напиши текст <b>без эмодзи</b>.\n"
        "/cancel — отмена."
    )
    await cb.answer()


@router.message(Labels.waiting, F.text)
async def labels_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    name = data.get("label_name")
    if not name:
        return
    await settings.set(f"label_{name}", message.text.strip())
    await message.answer("Кнопка переименована ✅ Вот обновлённое меню:",
                         reply_markup=keyboards.main_kb())


# ---- Премиум-иконки кнопок (Bot API 9.4) ----------------------------------

@router.callback_query(F.data == "adm:icons")
async def icons_start(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    note = "" if premium_emoji.ENABLED else \
        "\n⚠️ PREMIUM_EMOJI выключен — иконки не будут показаны, пока не включишь."
    await cb.message.answer("🎨 Для какой кнопки задать премиум-иконку?" + note,
                            reply_markup=keyboards.icons_pick_kb())
    await cb.answer()


@router.callback_query(F.data == "ico:reset")
async def icons_reset(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    for name in settings.DEFAULT_LABELS:
        await settings.set(f"icon_{name}", None)
    await cb.message.edit_text("Иконки кнопок убраны ✅ (обновится при /start)")
    await cb.answer()


@router.callback_query(F.data.startswith("ico:"))
async def icons_pick(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    name = cb.data.split(":")[1]
    if name not in settings.DEFAULT_LABELS:
        return await cb.answer()
    await state.set_state(Icons.waiting)
    await state.update_data(icon_name=name)
    await cb.message.answer(
        f"Пришли <b>премиум-эмодзи</b> для кнопки «{settings.label(name)}» "
        "(нужен Telegram Premium у отправителя). «-» — убрать иконку. /cancel — отмена."
    )
    await cb.answer()


@router.message(Icons.waiting, F.text == "-")
async def icons_clear(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    name = data.get("icon_name")
    if name:
        await settings.set(f"icon_{name}", None)
    await message.answer("Иконка убрана ✅ Вот обновлённое меню:", reply_markup=keyboards.main_kb())


@router.message(Icons.waiting)
async def icons_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data.get("icon_name")
    entities = message.entities or message.caption_entities or []
    cid = next((e.custom_emoji_id for e in entities
                if e.type == "custom_emoji" and e.custom_emoji_id), None)
    if not cid:
        await message.answer("Не вижу премиум-эмодзи. Пришли именно кастомный эмодзи "
                             "(нужен Telegram Premium) или «-» чтобы убрать.")
        return
    await state.clear()
    await settings.set(f"icon_{name}", cid)
    await message.answer(
        "Иконка кнопки сохранена ✅ Вот обновлённое меню:\n"
        "(если рядом дублируется обычный эмодзи — переименуй кнопку без эмодзи "
        "через «✏️ Кнопки меню»)",
        reply_markup=keyboards.main_kb(),
    )


# ---- Панель управления пользователями -------------------------------------

_PAGE = 8


async def _users_view(offset: int):
    total = await db.participants_count()
    rows = await db.participants_page(offset, _PAGE)
    c = await db.status_counts()
    header = (
        "👥 <b>Пользователи</b>\n"
        f"Всего: <b>{c['total']}</b> · ✅ {c['approved']} · ⏳ {c['pending']} · ⛔ {c['disq']}\n"
        f"Легенда: ✅ подтверждён · ⏳ ждёт · ⛔ дисквал.\n"
        f"Стр. {offset // _PAGE + 1}"
    )
    return header, keyboards.users_page_kb(rows, offset, total, c["pending"], _PAGE)


def _fmt(dt) -> str:
    return dt.astimezone(config.tz).strftime("%d.%m %H:%M") if dt else "—"


async def _card(tg_id: int):
    p = await db.user_detail(tg_id)
    if p is None:
        return None, None
    status = "⛔ дисквалифицирован" if p["disqualified_at"] else \
        ("✅ подтверждён" if p["approved_at"] else "⏳ ожидает подтверждения")
    uname = f"@{escape(p['username'])}" if p["username"] else "—"
    phone = f"<code>{escape(p['phone'])}</code>" if p["phone"] else "—"
    text = (
        f"👤 <b>{escape(p['full_name'])}</b>\n"
        f"🔗 {uname}\n"
        f"📱 {phone}\n"
        f"🆔 <code>{p['telegram_id']}</code>\n"
        f"🌳 Команда: <b>{escape(p['team_name'] or '—')}</b>\n"
        f"📌 Статус: {status}\n"
        f"🏢 Из ASR: {'да' if p['is_asr'] else 'нет'}\n"
        f"🗓 Регистрация: {_fmt(p['created_at'])}\n"
        f"✅ Вступил/подтверждён: {_fmt(p['approved_at'])}\n"
        f"⭐ Баллов: <b>{await db.total_points(tg_id)}</b>"
    )
    return text, keyboards.user_card_kb(p)


@router.callback_query(F.data == "adm:users")
async def users_open(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    header, kb = await _users_view(0)
    await cb.message.answer(header, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("usrpg:"))
async def users_page(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    offset = int(cb.data.split(":")[1])
    header, kb = await _users_view(offset)
    try:
        await cb.message.edit_text(header, reply_markup=kb)
    except Exception:  # noqa: BLE001
        await cb.message.answer(header, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:pending")
async def pending_list(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    rows = await db.pending_participants()
    if not rows:
        await cb.message.answer("⏳ Заявок на подтверждение нет ✅")
        return await cb.answer()
    await cb.message.answer(f"⏳ <b>Заявки на подтверждение ({len(rows)})</b>")
    from bot import texts
    for r in rows[:15]:
        p = await db.get_participant(r["telegram_id"])
        await cb.message.answer(texts.admin_new_registration(p, r["team_name"] or "—"),
                                reply_markup=keyboards.approve_kb(r["telegram_id"]))
    await cb.answer()


@router.callback_query(F.data.startswith("usr:"))
async def user_card(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    text, kb = await _card(int(cb.data.split(":")[1]))
    if text is None:
        return await cb.answer("Участник не найден.", show_alert=True)
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


async def _refresh_card(cb: CallbackQuery, tg_id: int) -> None:
    text, kb = await _card(tg_id)
    if text:
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception:  # noqa: BLE001
            await cb.message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("usrdq:"))
async def user_dq(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    tg = int(cb.data.split(":")[1])
    await db.set_disqualified(tg)
    try:
        from aiogram.types import ReplyKeyboardRemove
        await cb.bot.send_message(tg, texts.DISQUALIFIED_NOTICE, reply_markup=ReplyKeyboardRemove())
    except Exception:  # noqa: BLE001
        pass
    await _refresh_card(cb, tg)
    await cb.answer("Дисквалифицирован ⛔")


@router.callback_query(F.data.startswith("usrun:"))
async def user_un(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    tg = int(cb.data.split(":")[1])
    await db.undisqualify(tg)
    try:
        from bot.menu import send_main_menu
        await cb.bot.send_message(tg, texts.REINSTATED_NOTICE)
        await send_main_menu(cb.bot, tg, texts.welcome_back())
    except Exception:  # noqa: BLE001
        pass
    await _refresh_card(cb, tg)
    await cb.answer("Восстановлен ♻️")


@router.callback_query(F.data.startswith("usrmv:"))
async def user_move(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    tg = int(cb.data.split(":")[1])
    await state.update_data(move_target=tg)
    teams = await db.teams_with_capacity()
    await cb.message.answer("В какую команду перевести?",
                            reply_markup=keyboards.teams_pick_kb(teams, "mvt"))
    await cb.answer()


@router.callback_query(F.data.startswith("usrdel:"))
async def user_del(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    tg = int(cb.data.split(":")[1])
    await db.reset_participant(tg)
    await cb.message.edit_text("🗑 Участник удалён.")
    await cb.answer("Удалён")


# ---- Управление командами -------------------------------------------------

class TeamAdmin(StatesGroup):
    add_name = State()
    rename = State()
    capacity = State()


async def _teams_view():
    teams = await db.teams_with_capacity()
    header = ("🌳 <b>Команды</b>\n"
              "Выбери команду для настройки или добавь новую.\n"
              f"Всего команд: <b>{len(teams)}</b>")
    return header, keyboards.teams_admin_kb(teams)


@router.callback_query(F.data == "adm:teams")
async def teams_open(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(None)
    header, kb = await _teams_view()
    try:
        await cb.message.edit_text(header, reply_markup=kb)
    except Exception:  # noqa: BLE001
        await cb.message.answer(header, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "tm:add")
async def team_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(TeamAdmin.add_name)
    await cb.message.answer("Название новой команды? (можно с эмодзи). /cancel — отмена.")
    await cb.answer()


@router.message(TeamAdmin.add_name, F.text)
async def team_add_save(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.text.strip()
    if not name:
        return await message.answer("Пустое название. Попробуй ещё раз через «🌳 Команды».")
    await db.create_team(name, 10)
    header, kb = await _teams_view()
    await message.answer(f"Команда <b>{escape(name)}</b> добавлена ✅ (вместимость 10)")
    await message.answer(header, reply_markup=kb)


@router.callback_query(F.data.startswith("tm:"))
async def team_card(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    team_id = int(cb.data.split(":")[1])
    teams = await db.teams_with_capacity()
    t = next((x for x in teams if x["id"] == team_id), None)
    if t is None:
        return await cb.answer("Команда не найдена.", show_alert=True)
    text = (f"🌳 <b>{escape(t['name'])}</b>\n"
            f"Занято мест: <b>{t['taken']}/{t['capacity']}</b>")
    try:
        await cb.message.edit_text(text, reply_markup=keyboards.team_card_kb(team_id))
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=keyboards.team_card_kb(team_id))
    await cb.answer()


@router.callback_query(F.data.startswith("tmren:"))
async def team_rename_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(TeamAdmin.rename)
    await state.update_data(team_id=int(cb.data.split(":")[1]))
    await cb.message.answer("Новое название команды? /cancel — отмена.")
    await cb.answer()


@router.message(TeamAdmin.rename, F.text)
async def team_rename_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    name = message.text.strip()
    await db.rename_team(data["team_id"], name)
    header, kb = await _teams_view()
    await message.answer(f"Переименовано в <b>{escape(name)}</b> ✅")
    await message.answer(header, reply_markup=kb)


@router.callback_query(F.data.startswith("tmcap:"))
async def team_cap_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(TeamAdmin.capacity)
    await state.update_data(team_id=int(cb.data.split(":")[1]))
    await cb.message.answer("Новая вместимость команды? Пришли число (например 10). /cancel — отмена.")
    await cb.answer()


@router.message(TeamAdmin.capacity, F.text)
async def team_cap_save(message: Message, state: FSMContext) -> None:
    if not message.text.strip().isdigit():
        return await message.answer("Нужно число, например 10.")
    cap = int(message.text.strip())
    if not 1 <= cap <= 100:
        return await message.answer("Вместимость должна быть от 1 до 100.")
    data = await state.get_data()
    await state.clear()
    await db.set_team_capacity(data["team_id"], cap)
    header, kb = await _teams_view()
    await message.answer(f"Вместимость обновлена: <b>{cap}</b> ✅")
    await message.answer(header, reply_markup=kb)


@router.callback_query(F.data.startswith("tmdel:"))
async def team_delete(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    team_id = int(cb.data.split(":")[1])
    n = await db.team_member_count(team_id)
    if n > 0:
        return await cb.answer(f"Нельзя удалить: в команде {n} участник(ов). "
                               "Сначала переведите их в другие команды.", show_alert=True)
    await db.delete_team(team_id)
    header, kb = await _teams_view()
    try:
        await cb.message.edit_text("Команда удалена ✅\n\n" + header, reply_markup=kb)
    except Exception:  # noqa: BLE001
        await cb.message.answer(header, reply_markup=kb)
    await cb.answer("Удалено")


# ---- Настройка каналов (заявки / проверка результатов) --------------------

class AppUrl(StatesGroup):
    waiting = State()


@router.callback_query(F.data == "adm:appurl")
async def appurl_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    cur = settings.webapp_url() or "не задан"
    await state.set_state(AppUrl.waiting)
    await cb.message.answer(
        "🔗 <b>Ссылка Mini App</b>\n\n"
        f"Текущая: <code>{escape(cur)}</code>\n\n"
        "Пришли URL веб-приложения (например <code>https://wegrow-webapp.onrender.com</code>).\n"
        "Он включит кнопки «Мой прогресс/Лидерборд» с корректной авторизацией — "
        "это и есть причина ошибки «открой приложение из бота».\n"
        "«-» — очистить. /cancel — отмена."
    )
    await cb.answer()


@router.message(AppUrl.waiting, F.text)
async def appurl_save(message: Message, state: FSMContext) -> None:
    await state.clear()
    val = message.text.strip()
    if val == "-":
        await settings.set("webapp_url", None)
        await message.answer("Ссылка приложения очищена ✅ (кнопки откроют приложение по env, если задан)")
        return
    if not val.startswith("https://"):
        await message.answer("Ссылка должна начинаться с <code>https://</code>. Попробуй ещё раз через «⚙️ Оформление».")
        return
    await settings.set("webapp_url", val)
    # Обновляем постоянную кнопку меню на новый URL.
    try:
        from aiogram.types import MenuButtonWebApp, WebAppInfo
        await message.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=val)))
    except Exception:  # noqa: BLE001
        pass
    await message.answer("Ссылка приложения сохранена ✅\nОткрой /start — кнопки обновятся.",
                         reply_markup=keyboards.main_kb())


class ChannelSetup(StatesGroup):
    waiting = State()


def _channels_text() -> str:
    join = settings.channel_id("join")
    review = settings.channel_id("review")
    return (
        "📢 <b>Каналы</b>\n\n"
        f"📥 Заявки на вступление: <b>{join if join else 'не задан (шлём админам)'}</b>\n"
        f"🧾 Проверка результатов: <b>{review if review else 'не задан (шлём админам)'}</b>\n\n"
        "Чтобы задать канал: добавь бота в канал <b>администратором</b> (с правом "
        "публикации), затем перешли сюда любое сообщение из этого канала — я запомню его."
    )


@router.callback_query(F.data == "adm:channels")
async def channels_open(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(None)
    try:
        await cb.message.edit_text(_channels_text(), reply_markup=keyboards.channels_kb())
    except Exception:  # noqa: BLE001
        await cb.message.answer(_channels_text(), reply_markup=keyboards.channels_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("ch:"))
async def channel_set_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    kind = cb.data.split(":")[1]  # join | review
    if kind not in ("join", "review"):
        return await cb.answer()
    await state.set_state(ChannelSetup.waiting)
    await state.update_data(channel_kind=kind)
    title = "заявок на вступление" if kind == "join" else "проверки результатов"
    await cb.message.answer(
        f"Настраиваю канал <b>{title}</b>.\n\n"
        "Перешли сюда любое сообщение из нужного канала "
        "(бот должен быть в нём администратором), либо пришли числовой "
        "<b>chat_id</b> канала (например <code>-1001234567890</code>).\n"
        "«-» — сбросить (снова слать админам). /cancel — отмена."
    )
    await cb.answer()


@router.message(ChannelSetup.waiting)
async def channel_set_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = data.get("channel_kind")
    if not kind:
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "-":
        await state.clear()
        await settings.set(f"channel_{kind}", None)
        await message.answer("Канал сброшен ✅ Уведомления снова идут админам.",
                             reply_markup=keyboards.channels_kb())
        return

    chat_id = None
    if message.forward_from_chat is not None:
        chat_id = message.forward_from_chat.id
    elif text.lstrip("-").isdigit():
        chat_id = int(text)
    if chat_id is None:
        await message.answer("Не понял. Перешли сообщение из канала или пришли числовой "
                             "chat_id. «-» — сброс, /cancel — отмена.")
        return

    # Проверяем, что бот может писать в канал.
    try:
        probe = await message.bot.send_message(chat_id, "✅ Канал подключён к боту Step Together.")
        await state.clear()
        await settings.set(f"channel_{kind}", str(chat_id))
        try:
            await probe.delete()
        except Exception:  # noqa: BLE001
            pass
        title = "заявок на вступление" if kind == "join" else "проверки результатов"
        await message.answer(f"Готово! Канал {title}: <code>{chat_id}</code> ✅",
                             reply_markup=keyboards.channels_kb())
    except Exception as e:  # noqa: BLE001
        await message.answer(
            "Не удалось отправить сообщение в этот канал 😔\n"
            f"<code>{escape(str(e))}</code>\n\n"
            "Убедись, что бот добавлен в канал <b>администратором</b> с правом публикации, "
            "и попробуй снова.")


# ---- Модерация результатов (шаги) -----------------------------------------

class Warn(StatesGroup):
    waiting = State()


@router.callback_query(F.data == "adm:subs")
async def subs_queue(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    rows = await db.pending_submissions(15)
    if not rows:
        await cb.message.answer("🧾 Результатов на проверку нет ✅")
        return await cb.answer()
    await cb.message.answer(f"🧾 <b>На проверку: {len(rows)}</b>")
    for r in rows:
        e = await db.entry_by_id(r["id"])
        await notify.send_screenshot(cb.bot, cb.from_user.id, r["screenshot_file_id"],
                                     texts.admin_new_submission(e), keyboards.moderate_kb(r["id"]))
    await cb.answer()


async def _mark_caption(cb: CallbackQuery, suffix: str) -> None:
    try:
        await cb.message.edit_caption(caption=(cb.message.caption or "") + suffix,
                                      reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("mod_ok:"))
async def mod_accept(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    e = await db.entry_by_id(int(cb.data.split(":")[1]))
    if e is None:
        return await cb.answer("Запись не найдена.", show_alert=True)
    if e["status"] != "pending":
        await _mark_caption(cb, "\n\nℹ️ уже обработано")
        return await cb.answer("Уже обработано.")
    pts = points_for_steps(e["steps"])
    await db.set_entry_status(e["id"], "accepted", pts)
    st = await db.recompute_streak(e["participant_id"])
    await db.recompute_weekly_bonus(e["participant_id"], e["entry_date"])
    try:
        await cb.bot.send_message(e["participant_id"],
                                  texts.accepted_note(e["steps"], pts, st.current_len))
    except Exception:  # noqa: BLE001
        pass
    await _mark_caption(cb, f"\n\n✅ Принято, +{pts} ({escape(cb.from_user.first_name)})")
    await cb.answer("Принято ✅")


@router.callback_query(F.data.startswith("mod_no:"))
async def mod_reject(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    e = await db.entry_by_id(int(cb.data.split(":")[1]))
    if e is None:
        return await cb.answer("Запись не найдена.", show_alert=True)
    if e["status"] != "pending":
        await _mark_caption(cb, "\n\nℹ️ уже обработано")
        return await cb.answer("Уже обработано.")
    await db.set_entry_status(e["id"], "rejected", 0)
    await db.recompute_streak(e["participant_id"])
    await db.recompute_weekly_bonus(e["participant_id"], e["entry_date"])
    try:
        await cb.bot.send_message(e["participant_id"], texts.REJECTED_NOTE)
    except Exception:  # noqa: BLE001
        pass
    await _mark_caption(cb, f"\n\n❌ Отклонено ({escape(cb.from_user.first_name)})")
    await cb.answer("Отклонено ❌")


@router.callback_query(F.data.startswith("mod_warn:"))
async def mod_warn(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(Warn.waiting)
    await state.update_data(warn_entry=int(cb.data.split(":")[1]))
    await cb.message.answer("✍️ Напиши текст предупреждения участнику. "
                            "Результат при этом НЕ принимается. /cancel — отмена.")
    await cb.answer()


@router.message(Warn.waiting, F.text)
async def warn_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    e = await db.entry_by_id(data.get("warn_entry"))
    if e is None:
        return await message.answer("Запись не найдена.")
    try:
        await message.bot.send_message(e["participant_id"], texts.warning_note(escape(message.text)))
    except Exception:  # noqa: BLE001
        pass
    await message.answer("Предупреждение отправлено ⚠️ Результат остаётся на проверке — "
                         "прими или отклони его кнопками под скриншотом.")


# ---- Билдер рассылки ------------------------------------------------------

async def _show_builder(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("bc", {})
    await message.answer(
        "📣 <b>Рассылка</b> — собери сообщение:\n"
        f"• Текст: {'есть ✅' if draft.get('text') else 'нет'}\n"
        f"• Медиа: {'есть ✅' if draft.get('media') else 'нет'}\n"
        f"• Кнопок: {len(draft.get('buttons', []))}\n\n"
        "Поддерживается <b>markdown</b> (**жирный**, *курсив*, `код`) и премиум-эмодзи.",
        reply_markup=keyboards.bc_builder_kb(draft),
    )


async def start_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BC.text)
    await state.update_data(bc={"text": None, "media": None, "buttons": []})
    await message.answer("Пришли <b>текст</b> рассылки (или «-» без текста).\n"
                         "Форматируй как удобно: встроенным редактором Telegram "
                         "(Жирный/Курсив/…) или markdown (**жирный**). /cancel — отмена.")


@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await start_broadcast(cb.message, state)
    await cb.answer()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await start_broadcast(message, state)


@router.message(BC.text, F.text)
async def bc_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("bc", {})
    if message.text.strip() == "-":
        draft["text"], draft["html"] = None, False
    elif message.entities:
        # Нативное форматирование Telegram (Жирный/Курсив/эмодзи) → готовый HTML.
        draft["text"], draft["html"] = message.html_text, True
    else:
        # Обычный текст — поддержим markdown-разметку (**жирный** и т.п.).
        draft["text"], draft["html"] = message.text, False
    await state.update_data(bc=draft)
    await state.set_state(None)
    await _show_builder(message, state)


@router.callback_query(F.data == "bc:media")
async def bc_media(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BC.wait_media)
    await cb.message.answer("Пришли фото / гиф / видео для рассылки.")
    await cb.answer()


@router.message(BC.wait_media, F.photo | F.animation | F.video)
async def bc_media_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("bc", {})
    if message.photo:
        draft["media"] = {"type": "photo", "file_id": message.photo[-1].file_id}
    elif message.animation:
        draft["media"] = {"type": "animation", "file_id": message.animation.file_id}
    else:
        draft["media"] = {"type": "video", "file_id": message.video.file_id}
    await state.update_data(bc=draft)
    await state.set_state(None)
    await _show_builder(message, state)


@router.callback_query(F.data == "bc:buttons")
async def bc_buttons(cb: CallbackQuery) -> None:
    await cb.message.answer("Кнопки под сообщением:", reply_markup=keyboards.bc_buttons_kb())
    await cb.answer()


@router.callback_query(F.data == "bc:btn_custom")
async def bc_btn_custom(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BC.wait_button)
    await cb.message.answer("Пришли кнопку в формате: <code>Текст | https://ссылка</code>")
    await cb.answer()


@router.message(BC.wait_button, F.text)
async def bc_btn_save(message: Message, state: FSMContext) -> None:
    sep = "|" if "|" in message.text else None
    if not sep or len(message.text.split("|")) != 2:
        await message.answer("Формат: Текст | https://ссылка")
        return
    text, url = (x.strip() for x in message.text.split("|"))
    if not url.startswith("http"):
        await message.answer("Ссылка должна начинаться с http(s)://")
        return
    data = await state.get_data()
    draft = data.get("bc", {})
    draft.setdefault("buttons", []).append({"text": text, "url": url})
    await state.update_data(bc=draft)
    await state.set_state(None)
    await _show_builder(message, state)


@router.callback_query(F.data == "bc:btn_app")
async def bc_btn_app(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("bc", {})
    draft.setdefault("buttons", []).append({"text": "📊 Открыть приложение", "app": True})
    await state.update_data(bc=draft)
    await cb.message.answer("Кнопка приложения добавлена ✅")
    await _show_builder(cb.message, state)
    await cb.answer()


@router.callback_query(F.data == "bc:btn_clear")
async def bc_btn_clear(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("bc", {})
    draft["buttons"] = []
    await state.update_data(bc=draft)
    await cb.answer("Кнопки очищены")
    await _show_builder(cb.message, state)


@router.callback_query(F.data == "bc:back")
async def bc_back(cb: CallbackQuery, state: FSMContext) -> None:
    await _show_builder(cb.message, state)
    await cb.answer()


def _build_markup(draft: dict) -> InlineKeyboardMarkup | None:
    rows = []
    for btn in draft.get("buttons", []):
        if btn.get("app") and settings.webapp_url():
            b = keyboards.open_app_inline(btn["text"])
            if b:
                rows.append([b])
        elif btn.get("url"):
            rows.append([InlineKeyboardButton(text=btn["text"], url=btn["url"])])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _build_text(draft: dict) -> str:
    if not draft.get("text"):
        return ""
    # Нативное форматирование уже HTML (с премиум-эмодзи) — шлём как есть.
    if draft.get("html"):
        return draft["text"]
    return textfmt.md_to_html(draft["text"])


@router.callback_query(F.data == "bc:preview")
async def bc_preview(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("bc", {})
    await cb.message.answer("👁 Предпросмотр:")
    await notify.broadcast_rich(cb.bot, [cb.from_user.id], _build_text(draft),
                                draft.get("media"), _build_markup(draft))
    await cb.answer()


@router.callback_query(F.data == "bc:cancel")
async def bc_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("Рассылка отменена ✖️")
    await cb.answer()


@router.callback_query(F.data == "bc:send")
async def bc_send(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = await state.get_data()
    draft = data.get("bc", {})
    if not draft.get("text") and not draft.get("media"):
        return await cb.answer("Нужен текст или медиа.", show_alert=True)
    await state.clear()
    ids = await db.all_active_ids()
    await cb.message.answer(f"Отправляю {len(ids)} участникам…")
    sent = await notify.broadcast_rich(cb.bot, ids, _build_text(draft),
                                       draft.get("media"), _build_markup(draft))
    await db.pool().execute(
        "INSERT INTO broadcasts (admin_id, text, audience, recipients) VALUES ($1,$2,'all',$3)",
        cb.from_user.id, draft.get("text") or "[media]", sent,
    )
    await cb.message.answer(f"Готово! Доставлено: {sent}/{len(ids)} 🚀")
    await cb.answer()
