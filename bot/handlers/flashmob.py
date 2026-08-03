"""«Командный флешмоб» — бонус команде за массовость, а не за километры.

Условие дня: если не меньше threshold_pct участников команды сдали принятый
результат от min_steps шагов, команда получает bonus_points в командный зачёт
(таблица team_bonuses, учитывается в db.team_leaderboard).

Бонус считается не по расписанию, а после каждой модерации: результаты
подтверждают в разное время, поэтому recompute_flashmob идемпотентен — он
одинаково начисляет и снимает бонус при пересчёте.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot import db, keyboards, notify, settings, texts
from bot.config import config

router = Router()


def _is_admin(tg_id: int) -> bool:
    return settings.is_admin(tg_id)


def _today():
    return datetime.now(config.tz).date()


async def sync(bot: Bot, day: date) -> None:
    """Пересчитывает флешмоб дня и поздравляет команды, взявшие бонус именно
    сейчас. Вызывается после любой правки результатов за этот день."""
    res = await db.recompute_flashmob(day)
    fm = res["flashmob"]
    if fm is None or not res["new"]:
        return
    for team_id in res["new"]:
        row = next((r for r in res["rows"] if r["id"] == team_id), None)
        if row is None:
            continue
        ids = await db.team_member_ids([team_id])
        await notify.broadcast(
            bot, ids, texts.flashmob_won_note(fm, row["name"], row["done"], row["total"]))


async def _card_text(fm) -> str:
    res = await db.recompute_flashmob(fm["flash_date"])
    lines = []
    for r in res["rows"]:
        mark = "🏆" if r["awarded"] else "⏳"
        need = max(0, -(-fm["threshold_pct"] * r["total"] // 100) - r["done"])
        tail = "бонус начислен" if r["awarded"] else (
            f"не хватает {need}" if r["total"] else "нет участников")
        lines.append(f"{mark} {escape(r['name'])}: <b>{r['done']}/{r['total']}</b> "
                     f"({r['pct']}%) — {tail}")
    ann = (f"✅ отправлен, получили {fm['recipients']}" if fm["announced_at"]
           else "❌ ещё не отправлен — команды не знают о флешмобе")
    return (
        "🤝 <b>Командный флешмоб</b>\n"
        f"📅 Дата: <b>{fm['flash_date'].strftime('%d.%m.%Y')}</b>\n"
        f"⚡ Условие: <b>{texts.flashmob_rule(fm)}</b>\n"
        f"📣 Пуш: {ann}\n\n"
        "<b>Прогресс команд</b>\n" + ("\n".join(lines) or "— нет команд —") + "\n\n"
        "<i>Считаются только принятые результаты — прогресс растёт по мере "
        "модерации.</i>"
    )


@router.callback_query(F.data == "adm:flash")
async def flash_open(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    fm = await db.flashmob_for(_today())
    if fm is not None:
        text, kb = await _card_text(fm), keyboards.flashmob_card_kb(bool(fm["announced_at"]))
    else:
        await state.update_data(fm=None)
        text = (
            "🤝 <b>Командный флешмоб</b>\n\n"
            f"На сегодня ({_today().strftime('%d.%m.%Y')}) флешмоба нет.\n\n"
            "Баллы за <b>участие</b>, а не за километры: если сегодня достаточно "
            "большая доля команды сдаст результат от порога шагов — команда "
            "получит бонус в командный зачёт.\n\n"
            "Какая доля команды должна сдать?"
        )
        kb = keyboards.flashmob_pct_kb()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "fmnew")
async def flash_new(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.update_data(fm=None)
    await cb.message.edit_text(
        "🤝 <b>Новый флешмоб на сегодня</b>\n\nКакая доля команды должна сдать?",
        reply_markup=keyboards.flashmob_pct_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("fmpct:"))
async def flash_pct(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.update_data(fm={"pct": int(cb.data.split(":")[1]), "teams": []})
    await cb.message.edit_text(
        "👟 <b>От скольких шагов результат идёт в зачёт флешмоба?</b>\n\n"
        "<i>Порог участия обычно ниже обычного: смысл в том, чтобы дошли все, "
        "а не в рекордах.</i>",
        reply_markup=keyboards.flashmob_steps_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("fmsteps:"))
async def flash_steps(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("fm") or {"pct": 80, "teams": []}
    data["steps"] = int(cb.data.split(":")[1])
    await state.update_data(fm=data)
    await cb.message.edit_text(
        "🏆 <b>Сколько очков получит команда?</b>\n\n"
        "<i>Очки идут команде в общий зачёт, личные баллы участников не меняются.</i>",
        reply_markup=keyboards.flashmob_bonus_kb())
    await cb.answer()


async def _show_teams(cb: CallbackQuery, state: FSMContext) -> None:
    data = (await state.get_data()).get("fm") or {}
    teams = await db.teams_with_capacity()
    picked = set(data.get("teams") or [])
    await cb.message.edit_text(
        "🌳 <b>Для каких команд объявляем флешмоб?</b>\n\n"
        "Отмеченные команды получат анонс и смогут взять бонус. "
        "Ничего не отмечено = все команды.",
        reply_markup=keyboards.flashmob_teams_kb(teams, picked))


@router.callback_query(F.data.startswith("fmbonus:"))
async def flash_bonus(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("fm") or {"pct": 80, "steps": 8000, "teams": []}
    data["bonus"] = int(cb.data.split(":")[1])
    await state.update_data(fm=data)
    await _show_teams(cb, state)
    await cb.answer()


@router.callback_query(F.data.startswith("fmteam:"))
async def flash_team_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("fm")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    raw = cb.data.split(":")[1]
    teams = await db.teams_with_capacity()
    picked = set(data.get("teams") or [])
    if raw == "all":
        picked = set() if len(picked) == len(teams) else {t["id"] for t in teams}
    else:
        picked.symmetric_difference_update({int(raw)})
    data["teams"] = sorted(picked)
    await state.update_data(fm=data)
    await _show_teams(cb, state)
    await cb.answer()


@router.callback_query(F.data == "fmteams:done")
async def flash_preview(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("fm")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    teams = await db.teams_with_capacity()
    picked = list(data.get("teams") or [])
    team_ids = [] if len(picked) == len(teams) else picked
    data["teams"] = team_ids
    await state.update_data(fm=data)
    preview = {"threshold_pct": data["pct"], "min_steps": data["steps"],
               "bonus_points": data["bonus"]}
    names = ("все команды" if not team_ids else
             ", ".join(t["name"] for t in teams if t["id"] in team_ids))
    # Сколько человек нужно каждой команде — считаем по текущему составу.
    prog = [r for r in await db.flashmob_progress(_today(), data["steps"])
            if not team_ids or r["id"] in team_ids]
    need = "\n".join(
        f"• {escape(r['name'])}: нужно "
        f"<b>{-(-data['pct'] * r['total'] // 100)}</b> из {r['total']}"
        for r in prog if r["total"])
    ids = await db.team_member_ids(team_ids)
    await cb.message.edit_text(
        "🤝 <b>Проверь флешмоб</b>\n\n"
        f"📅 Дата: <b>{_today().strftime('%d.%m.%Y')}</b> (только сегодня)\n"
        f"⚡ Условие: <b>{texts.flashmob_rule(preview)}</b>\n"
        f"🌳 Команды: <b>{escape(names)}</b>\n"
        f"👥 Получат пуш: <b>{len(ids)}</b> участник(ов)\n\n"
        + (f"<b>Сколько нужно сдавших:</b>\n{need}" if need else ""),
        reply_markup=keyboards.flashmob_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "fmprev")
async def flash_preview_push(cb: CallbackQuery, state: FSMContext) -> None:
    """Показывает админу пуш ровно в том виде, в каком его получат участники."""
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("fm")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    fm = {"threshold_pct": data["pct"], "min_steps": data["steps"],
          "bonus_points": data["bonus"]}
    await cb.message.answer("👁 Так пуш увидят участники выбранных команд:")
    await cb.message.answer(texts.flashmob_announce(fm))
    await cb.answer()


@router.callback_query(F.data.startswith("fmsave:"))
async def flash_save(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    data = (await state.get_data()).get("fm")
    if not data:
        return await cb.answer("Сессия истекла, начни заново.", show_alert=True)
    announce = cb.data.split(":")[1] == "1"
    day = _today()
    fm = await db.save_flashmob(day, data["pct"], data["steps"], data["bonus"],
                                list(data["teams"]), cb.from_user.id)
    await state.update_data(fm=None)
    await sync(cb.bot, day)          # вдруг условие уже выполнено

    sent = 0
    if announce:
        ids = await db.team_member_ids(list(fm["team_ids"]))
        sent = await notify.broadcast(cb.bot, ids, texts.flashmob_announce(fm))
        await db.mark_flashmob_announced(day, sent)
    fm = await db.flashmob_for(day)
    tail = (f"\n\n📣 Пуш доставлен: <b>{sent}</b> участник(ам)" if announce else
            "\n\n🤫 Пуш не отправлен — флешмоб идёт, но команды о нём не знают. "
            "Кнопка «🚀 Запустить: оповестить участников» ниже.")
    await cb.message.edit_text(
        ("🚀 <b>Флешмоб запущен</b>\n\n" if announce else "✅ <b>Флешмоб создан</b>\n\n")
        + await _card_text(fm) + tail,
        reply_markup=keyboards.flashmob_card_kb(bool(fm["announced_at"])))
    await cb.answer("Флешмоб создан 🤝")


@router.callback_query(F.data == "fmann")
async def flash_announce(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    fm = await db.flashmob_for(_today())
    if fm is None:
        return await cb.answer("Флешмоба на сегодня нет.", show_alert=True)
    ids = await db.team_member_ids(list(fm["team_ids"]))
    await cb.answer(f"Отправляю {len(ids)}…")
    sent = await notify.broadcast(cb.bot, ids, texts.flashmob_announce(fm))
    await db.mark_flashmob_announced(_today(), sent)
    fm = await db.flashmob_for(_today())
    await cb.message.edit_text(
        await _card_text(fm) + f"\n\n📣 Доставлено: <b>{sent}</b>/{len(ids)} 🚀",
        reply_markup=keyboards.flashmob_card_kb(True))


@router.callback_query(F.data == "fmdel")
async def flash_delete(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    if await db.delete_flashmob(_today()) is None:
        return await cb.answer("Флешмоба на сегодня нет.", show_alert=True)
    await cb.message.edit_text(
        "🗑 <b>Флешмоб удалён</b>\nНачисленные за сегодня командные очки сняты.",
        reply_markup=keyboards.admin_panel_kb())
    await cb.answer("Удалён")
