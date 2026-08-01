"""«Тайный челлендж» — разовый множитель баллов на один день марафона.

Админ выбирает множитель (×2/×3), условие и КОМАНДЫ, на которые он действует,
после чего может отправить анонс только участникам этих команд.

Важно про условие: бот знает лишь итоговое число шагов за день — времени, когда
человек их прошёл, у него нет. Поэтому вариант «после 19:00» работает по времени
ОТПРАВКИ результата (единственное время, которое реально известно боту).
"""
from __future__ import annotations

from datetime import datetime, time
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot import db, keyboards, notify, settings, texts
from bot.config import config

router = Router()


def _is_admin(tg_id: int) -> bool:
    return settings.is_admin(tg_id)


def _today():
    return datetime.now(config.tz).date()


async def _teams_note(team_ids: list[int]) -> str:
    if not team_ids:
        return "все команды"
    teams = await db.teams_with_capacity()
    names = [t["name"] for t in teams if t["id"] in team_ids]
    return ", ".join(names) if names else "—"


async def _card_text(ch) -> str:
    who = await _teams_note(list(ch["team_ids"]))
    ann = (f"отправлен {ch['announced_at'].astimezone(config.tz).strftime('%H:%M')}, "
           f"получили {ch['recipients']}" if ch["announced_at"] else "ещё не отправлен")
    return (
        "🎲 <b>Тайный челлендж</b>\n"
        f"📅 Дата: <b>{ch['challenge_date'].strftime('%d.%m.%Y')}</b>\n"
        f"⚡ Условие: <b>{texts.challenge_rule(ch)}</b>\n"
        f"🌳 Команды: <b>{escape(who)}</b>\n"
        f"📣 Анонс: {ann}\n\n"
        "Множитель применяется при принятии результата, а уже принятые за этот "
        "день результаты пересчитаны."
    )


@router.callback_query(F.data == "adm:chal")
async def chal_open(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.update_data(chal=None)
    ch = await db.challenge_for(_today())
    if ch is not None:
        text, kb = await _card_text(ch), keyboards.challenge_card_kb(bool(ch["announced_at"]))
    else:
        text = (
            "🎲 <b>Тайный челлендж</b>\n\n"
            f"На сегодня ({_today().strftime('%d.%m.%Y')}) челленджа нет.\n\n"
            "Это разовый множитель баллов на один день — для выбранных команд.\n"
            "Во сколько раз умножаем баллы за день?"
        )
        kb = keyboards.challenge_mult_kb()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "chnew")
async def chal_new(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.update_data(chal=None)
    await cb.message.edit_text(
        "🎲 <b>Новый челлендж на сегодня</b>\n\nВо сколько раз умножаем баллы за день?",
        reply_markup=keyboards.challenge_mult_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("chmul:"))
async def chal_mult(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.update_data(chal={"mult": int(cb.data.split(":")[1]), "teams": []})
    await cb.message.edit_text(
        "⏰ <b>Когда действует множитель?</b>\n\n"
        "<i>Бот знает только итог за день — во сколько человек ходил, ему неизвестно. "
        "Поэтому «после 19:00» = множитель получат те, кто <b>пришлёт результат</b> "
        "после 19:00 (и до 23:55).</i>",
        reply_markup=keyboards.challenge_time_kb())
    await cb.answer()


async def _show_teams(cb: CallbackQuery, state: FSMContext) -> None:
    data = (await state.get_data()).get("chal") or {}
    teams = await db.teams_with_capacity()
    picked = set(data.get("teams") or [])
    await cb.message.edit_text(
        "🌳 <b>Для каких команд действует челлендж?</b>\n\n"
        "Отметь команды — участники только этих команд получат множитель "
        "и анонс. Ничего не отмечено = все команды.",
        reply_markup=keyboards.challenge_teams_kb(teams, picked))


@router.callback_query(F.data.startswith("chtime:"))
async def chal_time(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    raw = cb.data.split(":")[1]
    data = (await state.get_data()).get("chal") or {"mult": 2, "teams": []}
    data["after"] = None if raw == "all" else int(raw)
    await state.update_data(chal=data)
    await _show_teams(cb, state)
    await cb.answer()


@router.callback_query(F.data.startswith("chteam:"))
async def chal_team_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("chal")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    raw = cb.data.split(":")[1]
    teams = await db.teams_with_capacity()
    picked = set(data.get("teams") or [])
    if raw == "all":
        picked = set() if len(picked) == len(teams) else {t["id"] for t in teams}
    else:
        tid = int(raw)
        picked.symmetric_difference_update({tid})
    data["teams"] = sorted(picked)
    await state.update_data(chal=data)
    await _show_teams(cb, state)
    await cb.answer()


@router.callback_query(F.data == "chteams:done")
async def chal_preview(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("chal")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    teams = await db.teams_with_capacity()
    picked = list(data.get("teams") or [])
    # Отмечены все команды — храним пустой список: «все», в том числе новые.
    team_ids = [] if len(picked) == len(teams) else picked
    data["teams"] = team_ids
    await state.update_data(chal=data)
    ids = await db.team_member_ids(team_ids)
    preview = {"multiplier": data["mult"], "after_time":
               None if data.get("after") is None else time(data["after"], 0)}
    rule = texts.challenge_rule(preview)
    await cb.message.edit_text(
        "🎲 <b>Проверь челлендж</b>\n\n"
        f"📅 Дата: <b>{_today().strftime('%d.%m.%Y')}</b> (только сегодня)\n"
        f"⚡ Условие: <b>{rule}</b>\n"
        f"🌳 Команды: <b>{escape(await _teams_note(team_ids))}</b>\n"
        f"👥 Получат анонс: <b>{len(ids)}</b> участник(ов)\n\n"
        "Уже принятые сегодня результаты этих команд будут пересчитаны.",
        reply_markup=keyboards.challenge_confirm_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("chsave:"))
async def chal_save(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("chal")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    announce = cb.data.split(":")[1] == "1"
    after = None if data.get("after") is None else time(data["after"], 0)
    day = _today()
    ch = await db.save_challenge(day, data["mult"], after, list(data["teams"]),
                                 cb.from_user.id)
    await state.update_data(chal=None)
    changed = await db.recount_day_points(day, ch)

    sent = 0
    if announce:
        ids = await db.team_member_ids(list(ch["team_ids"]))
        sent = await notify.broadcast(cb.bot, ids, texts.challenge_announce(ch))
        await db.mark_challenge_announced(day, sent)
        ch = await db.challenge_for(day)

    tail = (f"\n\n📣 Анонс доставлен: <b>{sent}</b>" if announce else
            "\n\n🤫 Анонс не отправлен — кнопка «📣 Отправить анонс» ниже.")
    if changed:
        tail += f"\n♻️ Пересчитано уже принятых результатов: <b>{changed}</b>"
    await cb.message.edit_text(
        "✅ <b>Челлендж создан</b>\n\n" + await _card_text(ch) + tail,
        reply_markup=keyboards.challenge_card_kb(bool(ch["announced_at"])))
    await cb.answer("Челлендж создан 🎲")


@router.callback_query(F.data == "chann")
async def chal_announce(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    ch = await db.challenge_for(_today())
    if ch is None:
        return await cb.answer("Челленджа на сегодня нет.", show_alert=True)
    ids = await db.team_member_ids(list(ch["team_ids"]))
    await cb.answer(f"Отправляю {len(ids)}…")
    sent = await notify.broadcast(cb.bot, ids, texts.challenge_announce(ch))
    await db.mark_challenge_announced(_today(), sent)
    ch = await db.challenge_for(_today())
    await cb.message.edit_text(
        await _card_text(ch) + f"\n\n📣 Доставлено: <b>{sent}</b>/{len(ids)} 🚀",
        reply_markup=keyboards.challenge_card_kb(True))


@router.callback_query(F.data == "chdel")
async def chal_delete(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    day = _today()
    if await db.delete_challenge(day) is None:
        return await cb.answer("Челленджа на сегодня нет.", show_alert=True)
    changed = await db.recount_day_points(day, None)   # вернуть базовые баллы
    await cb.message.edit_text(
        "🗑 <b>Челлендж удалён</b>\n"
        f"Баллы за сегодня вернулись к обычным. Пересчитано записей: <b>{changed}</b>.",
        reply_markup=keyboards.admin_panel_kb())
    await cb.answer("Удалён")
