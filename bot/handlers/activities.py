"""Отчёт по активностям: какие челленджи и флешмобы запускались, кому они
были доступны (по командам и поимённо) и как в них участвовали.

Только чтение — ничего не начисляет и не пересчитывает.
"""
from __future__ import annotations

from datetime import date
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from backend.scoring import points_for_steps
from bot import db, settings, texts
from bot.config import config

router = Router()

_LIMIT = 8            # активностей в списке
_NAMES = 40           # участников в поимённом списке


def _is_admin(tg_id: int) -> bool:
    return settings.is_admin(tg_id)


async def _teams_note(team_ids: list[int]) -> str:
    if not team_ids:
        return "все команды"
    teams = await db.teams_with_capacity()
    return ", ".join(t["name"] for t in teams if t["id"] in team_ids) or "—"


def _push_note(row, key: str = "announced_at") -> str:
    if not row[key]:
        return "❌ пуш не отправляли"
    when = row[key].astimezone(config.tz).strftime("%d.%m %H:%M")
    return f"✅ пуш {when}, получили {row['recipients']}"


def _pct(part: int, total: int) -> int:
    return round(part / total * 100) if total else 0


# ---- Список активностей ----------------------------------------------------

@router.callback_query(F.data == "adm:acts")
async def acts_list(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    chals = await db.list_challenges(_LIMIT)
    flashes = await db.list_flashmobs(_LIMIT)
    b = InlineKeyboardBuilder()
    lines = ["📊 <b>Активности марафона</b>", ""]

    lines.append("🎲 <b>Тайные челленджи</b>")
    if not chals:
        lines.append("— не запускались —")
    for ch in chals:
        d = ch["challenge_date"]
        lines.append(f"• {d.strftime('%d.%m')} — {texts.challenge_rule(ch)} "
                     f"({escape(await _teams_note(list(ch['team_ids'])))}) · "
                     f"{_push_note(ch)}")
        b.button(text=f"🎲 {d.strftime('%d.%m')} ×{ch['multiplier']}",
                 callback_data=f"actc:{d.isoformat()}")

    lines += ["", "🤝 <b>Командные флешмобы</b>"]
    if not flashes:
        lines.append("— не запускались —")
    for fm in flashes:
        d = fm["flash_date"]
        lines.append(f"• {d.strftime('%d.%m')} — {texts.flashmob_rule(fm)} "
                     f"({escape(await _teams_note(list(fm['team_ids'])))}) · "
                     f"{_push_note(fm)}")
        b.button(text=f"🤝 {d.strftime('%d.%m')} {fm['threshold_pct']}%",
                 callback_data=f"actf:{d.isoformat()}")

    lines += ["", "<i>Нажми на активность — покажу статистику участия.</i>"]
    b.adjust(2)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back"))
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=b.as_markup())
    await cb.answer()


def _detail_kb(kind: str, day: date) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="👥 Поимённо", callback_data=f"act{kind}p:{day.isoformat()}")
    b.button(text="⬅️ К списку", callback_data="adm:acts")
    b.adjust(1)
    return b


# ---- Челлендж: статистика --------------------------------------------------

def _chal_rows(ch, rows) -> list[dict]:
    """Размечает участников: попал ли результат под множитель."""
    out = []
    for r in rows:
        accepted = r["status"] == "accepted"
        applied = accepted and db.challenge_applies(ch, r["team_id"], r["created_at"])
        extra = (r["points"] - points_for_steps(r["steps"])) if applied else 0
        out.append({"name": r["full_name"], "team": r["team_name"] or "—",
                    "status": r["status"], "steps": r["steps"], "points": r["points"],
                    "accepted": accepted, "applied": applied, "extra": extra})
    return out


@router.callback_query(F.data.startswith("actc:"))
async def act_challenge(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    day = date.fromisoformat(cb.data.split(":")[1])
    ch = await db.challenge_for(day)
    if ch is None:
        return await cb.answer("Челлендж не найден — возможно, его удалили.", show_alert=True)
    scope = list(ch["team_ids"])
    marked = _chal_rows(ch, await db.day_participation(day, scope))
    total = len(marked)
    accepted = sum(1 for r in marked if r["accepted"])
    applied = sum(1 for r in marked if r["applied"])
    extra = sum(r["extra"] for r in marked)

    by_team: dict[str, list[dict]] = {}
    for r in marked:
        by_team.setdefault(r["team"], []).append(r)
    per_team = "\n".join(
        f"• {escape(name)}: под множитель <b>{sum(1 for x in rs if x['applied'])}</b> "
        f"из {len(rs)} (сдали {sum(1 for x in rs if x['accepted'])})"
        for name, rs in by_team.items())

    await cb.message.edit_text(
        f"🎲 <b>Челлендж {day.strftime('%d.%m.%Y')}</b>\n"
        f"⚡ Условие: <b>{texts.challenge_rule(ch)}</b>\n"
        f"🌳 Команды: <b>{escape(await _teams_note(scope))}</b>\n"
        f"📣 {_push_note(ch)}\n\n"
        f"👥 Доступен: <b>{total}</b> участник(ам)\n"
        f"✅ Сдали и приняты: <b>{accepted}</b> ({_pct(accepted, total)}%)\n"
        f"🎯 Попали под множитель: <b>{applied}</b> ({_pct(applied, total)}% "
        f"от доступных, {_pct(applied, accepted)}% от сдавших)\n"
        f"⭐ Дополнительно начислено: <b>+{extra}</b> балл(ов)\n\n"
        f"<b>По командам</b>\n{per_team or '—'}",
        reply_markup=_detail_kb("c", day).as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("actcp:"))
async def act_challenge_people(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    day = date.fromisoformat(cb.data.split(":")[1])
    ch = await db.challenge_for(day)
    if ch is None:
        return await cb.answer("Челлендж не найден.", show_alert=True)
    marked = _chal_rows(ch, await db.day_participation(day, list(ch["team_ids"])))
    lines, team = [], None
    for r in marked[:_NAMES]:
        if r["team"] != team:
            team, _ = r["team"], lines.append(f"\n🌳 <b>{escape(r['team'])}</b>")
        if r["applied"]:
            lines.append(f"✅ {escape(r['name'])} — {r['steps']} шагов, "
                         f"<b>+{r['points']}</b> (×{ch['multiplier']})")
        elif r["accepted"]:
            lines.append(f"☑️ {escape(r['name'])} — {r['steps']} шагов, +{r['points']} "
                         "(без множителя)")
        elif r["status"] == "pending":
            lines.append(f"⏳ {escape(r['name'])} — на проверке")
        elif r["status"] == "rejected":
            lines.append(f"❌ {escape(r['name'])} — отклонён")
        else:
            lines.append(f"▫️ {escape(r['name'])} — не сдавал(а)")
    tail = f"\n\n…и ещё {len(marked) - _NAMES}" if len(marked) > _NAMES else ""
    await cb.message.edit_text(
        f"🎲 <b>Челлендж {day.strftime('%d.%m.%Y')} — поимённо</b>\n"
        "✅ с множителем · ☑️ сдал(а) без множителя · ⏳ на проверке · "
        "❌ отклонён · ▫️ не сдавал(а)\n"
        + "\n".join(lines) + tail,
        reply_markup=_detail_kb("c", day).as_markup())
    await cb.answer()


# ---- Флешмоб: статистика ---------------------------------------------------

@router.callback_query(F.data.startswith("actf:"))
async def act_flashmob(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    day = date.fromisoformat(cb.data.split(":")[1])
    fm = await db.flashmob_for(day)
    if fm is None:
        return await cb.answer("Флешмоб не найден — возможно, его удалили.", show_alert=True)
    scope = list(fm["team_ids"])
    rows = await db.day_participation(day, scope)
    bonuses = await db.team_bonus_rows(day)

    by_team: dict[int, dict] = {}
    for r in rows:
        t = by_team.setdefault(r["team_id"], {"name": r["team_name"] or "—",
                                              "total": 0, "done": 0, "sent": 0})
        t["total"] += 1
        if r["status"] == "accepted":
            t["sent"] += 1
            if r["steps"] >= fm["min_steps"]:
                t["done"] += 1
    lines = []
    for tid, t in by_team.items():
        got = bonuses.get(tid)
        need = max(0, -(-fm["threshold_pct"] * t["total"] // 100) - t["done"])
        tail = (f"бонус <b>+{got}</b> начислен" if got
                else f"не хватает {need}" if t["total"] else "нет участников")
        lines.append(f"{'🏆' if got else '⏳'} {escape(t['name'])}: "
                     f"<b>{t['done']}/{t['total']}</b> ({_pct(t['done'], t['total'])}%) "
                     f"— {tail}")
    total = sum(t["total"] for t in by_team.values())
    done = sum(t["done"] for t in by_team.values())
    awarded = [tid for tid in by_team if bonuses.get(tid)]

    await cb.message.edit_text(
        f"🤝 <b>Флешмоб {day.strftime('%d.%m.%Y')}</b>\n"
        f"⚡ Условие: <b>{texts.flashmob_rule(fm)}</b>\n"
        f"🌳 Команды: <b>{escape(await _teams_note(scope))}</b>\n"
        f"📣 {_push_note(fm)}\n\n"
        f"👥 Доступен: <b>{total}</b> участник(ам)\n"
        f"🎯 Выполнили условие: <b>{done}</b> ({_pct(done, total)}%)\n"
        f"🏆 Команд взяли бонус: <b>{len(awarded)}</b> из {len(by_team)} "
        f"(+{sum(bonuses.get(t, 0) for t in by_team)} очков)\n\n"
        f"<b>По командам</b>\n" + ("\n".join(lines) or "—"),
        reply_markup=_detail_kb("f", day).as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("actfp:"))
async def act_flashmob_people(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    day = date.fromisoformat(cb.data.split(":")[1])
    fm = await db.flashmob_for(day)
    if fm is None:
        return await cb.answer("Флешмоб не найден.", show_alert=True)
    rows = await db.day_participation(day, list(fm["team_ids"]))
    lines, team = [], None
    for r in rows[:_NAMES]:
        name = r["team_name"] or "—"
        if name != team:
            team, _ = name, lines.append(f"\n🌳 <b>{escape(name)}</b>")
        if r["status"] == "accepted" and r["steps"] >= fm["min_steps"]:
            lines.append(f"✅ {escape(r['full_name'])} — {r['steps']} шагов")
        elif r["status"] == "accepted":
            lines.append(f"☑️ {escape(r['full_name'])} — {r['steps']} шагов "
                         f"(меньше {fm['min_steps']})")
        elif r["status"] == "pending":
            lines.append(f"⏳ {escape(r['full_name'])} — на проверке")
        elif r["status"] == "rejected":
            lines.append(f"❌ {escape(r['full_name'])} — отклонён")
        else:
            lines.append(f"▫️ {escape(r['full_name'])} — не сдавал(а)")
    tail = f"\n\n…и ещё {len(rows) - _NAMES}" if len(rows) > _NAMES else ""
    await cb.message.edit_text(
        f"🤝 <b>Флешмоб {day.strftime('%d.%m.%Y')} — поимённо</b>\n"
        f"✅ зачтён ({fm['min_steps']}+) · ☑️ сдал(а) меньше порога · "
        "⏳ на проверке · ❌ отклонён · ▫️ не сдавал(а)\n"
        + "\n".join(lines) + tail,
        reply_markup=_detail_kb("f", day).as_markup())
    await cb.answer()
