"""Планировщик регулярных рассылок (APScheduler)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.scoring import weekly_streak_bonus
from bot import db, notify, texts
from bot.config import config


def _marathon_active() -> bool:
    """Напоминания шлём только в даты марафона (17.07–07.08)."""
    today = datetime.now(config.tz).date()
    return config.marathon_start <= today <= config.marathon_end


async def remind_no_steps(bot: Bot) -> None:
    """21:00 — напоминание только тем, кто ещё не сдал шаги сегодня."""
    if not _marathon_active():
        return
    day = datetime.now(config.tz).date()
    ids = await db.ids_without_entry_today(day)
    await notify.broadcast(bot, ids, texts.REMINDER_2100)


async def remind_streak_at_risk(bot: Bot) -> None:
    """20:00 — персональное напоминание тем, у кого серия под угрозой."""
    if not _marathon_active():
        return
    day = datetime.now(config.tz).date()
    for r in await db.streak_at_risk(day, min_len=3):
        await notify.broadcast(bot, [r["participant_id"]],
                               texts.streak_at_risk_note(r["current_len"]))


async def weekly_summary_reminder(bot: Bot) -> None:
    """Вс 12:00 и 21:00 — напоминание прислать недельную сводку (правило 12)."""
    if not _marathon_active():
        return
    await notify.broadcast_all(bot, texts.WEEKLY_SUMMARY_REMINDER)


async def award_weekly_bonuses(bot: Bot) -> None:
    """Вс 23:55 — начисляем недельный бонус за серию по данным недели (правило 10)."""
    if not _marathon_active():
        return
    today = datetime.now(config.tz).date()
    monday = today - timedelta(days=today.weekday())  # воскресенье → понедельник этой недели
    for tg_id in await db.all_active_ids():
        steps = await db.week_steps(tg_id, monday)
        bonus = weekly_streak_bonus(steps)
        await db.award_weekly_bonus(tg_id, monday, bonus, sum(steps))
        if bonus:
            await notify.broadcast(bot, [tg_id], texts.weekly_bonus_note(bonus))


async def monday_leaderboard(bot: Bot) -> None:
    """Пн 10:00 — итоги недели: топ-3 команд и топ-3 участников."""
    if not _marathon_active():
        return
    teams = await db.team_leaderboard()
    top = await db.top_participants(3)
    text = texts.render_leaderboard(teams[:3], top, header="Итоги недели", top_title="Топ-3 участников")
    await notify.broadcast_all(bot, text)


async def pc_daily_digest(bot: Bot) -> None:
    """09:00 — дайджест для P&C: как прошёл вчерашний день + кто молчит 2+ дня."""
    today = datetime.now(config.tz).date()
    # Дайджест полезен со 2-го дня марафона и ещё день после финиша.
    if not (config.marathon_start < today <= config.marathon_end + timedelta(days=1)):
        return
    day = today - timedelta(days=1)
    s = await db.digest_stats(day)
    lines = [
        f"📊 <b>Дайджест за {day.strftime('%d.%m')}</b>",
        f"Сдали шаги: <b>{s['total']}</b> из {s['active']} участников",
        f"✅ Принято: <b>{s['accepted']}</b> · ⏳ На проверке: <b>{s['pending']}</b>"
        f" · ❌ Отклонено: <b>{s['rejected']}</b>",
    ]
    if s["silent"]:
        lines.append(f"\n😴 <b>Молчат 2+ дня ({len(s['silent'])}):</b>")
        for r in s["silent"][:15]:
            last = r["last_entry"].strftime("%d.%m") if r["last_entry"] else "ни разу"
            team = r["team_name"] or "—"
            lines.append(f"• {r['full_name']} ({team}) — посл. сдача: {last}")
        if len(s["silent"]) > 15:
            lines.append(f"…и ещё {len(s['silent']) - 15}")
    else:
        lines.append("\n🎉 Молчунов нет — сдают все!")
    if s["pending"]:
        lines.append("\n👉 Не забудь проверить заявки на модерации.")
    await notify.notify_admins(bot, "\n".join(lines))


async def nightly_backup(bot: Bot) -> None:
    """23:59 — резервная копия: полная Excel-выгрузка админам в личку.
    Если что-то случится с базой, у P&C всегда есть вчерашний слепок данных."""
    today = datetime.now(config.tz).date()
    if not (config.marathon_start <= today <= config.marathon_end + timedelta(days=1)):
        return
    from aiogram.types import BufferedInputFile
    from bot.export import build_workbook
    data, name = await build_workbook()
    doc = BufferedInputFile(data, filename=f"backup_{name}")
    for admin_id in config.admin_ids:
        try:
            await bot.send_document(admin_id, doc,
                                    caption="🗄 Ночная резервная копия данных марафона")
        except Exception:  # noqa: BLE001 — админ мог не начать диалог с ботом
            pass


async def send_due_broadcasts(bot: Bot) -> None:
    """Ежеминутно: отправляет отложенные рассылки, чьё время пришло."""
    import json
    from bot.handlers.admin_settings import _build_markup, _build_text
    now = datetime.now(timezone.utc)
    for row in await db.due_scheduled_broadcasts(now):
        draft = row["draft"]
        if isinstance(draft, str):
            draft = json.loads(draft)
        ids = await db.all_active_ids()
        sent = await notify.broadcast_rich(bot, ids, _build_text(draft),
                                           draft.get("media"), _build_markup(draft))
        await db.mark_scheduled_sent(row["id"], sent)
        await notify.broadcast(bot, [row["admin_id"]],
                               f"⏰ Отложенная рассылка #{row['id']} отправлена: {sent}/{len(ids)}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=config.tz)

    # Напоминания активны только в даты марафона (_marathon_active внутри задач).
    sched.add_job(remind_streak_at_risk, "cron", hour=20, minute=0, args=[bot])
    sched.add_job(remind_no_steps, "cron", hour=21, minute=0, args=[bot])
    sched.add_job(weekly_summary_reminder, "cron", day_of_week="sun", hour=12, minute=0, args=[bot])
    sched.add_job(weekly_summary_reminder, "cron", day_of_week="sun", hour=21, minute=0, args=[bot])
    sched.add_job(award_weekly_bonuses, "cron", day_of_week="sun", hour=23, minute=55, args=[bot])
    sched.add_job(monday_leaderboard, "cron", day_of_week="mon", hour=10, minute=0, args=[bot])
    sched.add_job(pc_daily_digest, "cron", hour=9, minute=0, args=[bot])
    sched.add_job(nightly_backup, "cron", hour=23, minute=59, args=[bot])

    # Отложенные рассылки админов — проверяем каждую минуту.
    sched.add_job(send_due_broadcasts, "interval", minutes=1, args=[bot])

    # Пинг Render, чтобы web-инстанс не засыпал.
    if config.webapp_url:
        sched.add_job(keep_webapp_awake, "interval", minutes=10)

    return sched


async def keep_webapp_awake() -> None:
    """Пинг веб-сервиса, чтобы free-инстанс Render не засыпал."""
    import aiohttp
    url = config.webapp_url.rstrip("/") + "/health"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                await r.read()
    except Exception:  # noqa: BLE001 — сеть/сон, не критично
        pass
