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

from bot import db, keyboards, notify, premium_emoji, settings, textfmt
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

@router.callback_query(F.data == "adm:move")
async def move_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.set_state(Move.query)
    await cb.message.answer("🔀 Кого перевести? Пришли <b>ID</b> или часть <b>ФИО</b>.")
    await cb.answer()


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
        await cb.bot.send_message(target, f"🔀 Тебя перевели в команду <b>{escape(tname)}</b>. Вперёд! 💪")
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
    await cb.message.answer(f"Пришли новый текст для кнопки «{settings.label(name)}». /cancel — отмена.")
    await cb.answer()


@router.message(Labels.waiting, F.text)
async def labels_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    name = data.get("label_name")
    if not name:
        return
    await settings.set(f"label_{name}", message.text.strip())
    await message.answer(f"Кнопка обновлена: {escape(message.text.strip())} ✅ (обновится при /start)")


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
    await message.answer("Иконка убрана ✅ (обновится при /start)")


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
    await message.answer("Иконка кнопки сохранена ✅ (обновится при /start)")


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
    await message.answer("Пришли <b>текст</b> рассылки (или «-» без текста). /cancel — отмена.")


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
    draft["text"] = None if message.text.strip() == "-" else message.text
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
        if btn.get("app") and config.webapp_url:
            b = keyboards.open_app_inline(btn["text"])
            if b:
                rows.append([b])
        elif btn.get("url"):
            rows.append([InlineKeyboardButton(text=btn["text"], url=btn["url"])])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _build_text(draft: dict) -> str:
    return textfmt.md_to_html(draft["text"]) if draft.get("text") else ""


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
