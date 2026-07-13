"""Планировщик регулярных рассылок (APScheduler)."""
from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import db, notify, texts
from bot.config import config


async def remind_no_steps(bot: Bot) -> None:
    """21:00 — напоминание только тем, кто ещё не сдал шаги сегодня."""
    day = datetime.now(config.tz).date()
    ids = await db.ids_without_entry_today(day)
    await notify.broadcast(bot, ids, texts.REMINDER_2100)


async def weekly_summary_reminder(bot: Bot) -> None:
    """Вс 12:00 и 21:00 — напоминание прислать недельную сводку."""
    text = f"{texts.GROW} Воскресенье — пришли недельную сводку из Google Fit, сверю и начислю бонус за серию."
    await notify.broadcast_all(bot, text)


async def monday_leaderboard(bot: Bot) -> None:
    """Пн 10:00 — итоги недели: топ-3 команд и топ-3 участников."""
    teams = await db.team_leaderboard()
    top = await db.top_participants(3)
    lines = [f"{texts.GROW} *Итоги недели*", "", "🏆 Команды:"]
    for i, t in enumerate(teams[:3], 1):
        lines.append(f"{i}. {t['name']} — {t['points']}")
    lines.append("\n👟 Участники:")
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. {p['full_name'] or '—'} — {p['points']}")
    await notify.broadcast_all(bot, "\n".join(lines), parse_mode="Markdown")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=config.tz)
    sched.add_job(remind_no_steps, "cron", hour=21, minute=0, args=[bot])
    sched.add_job(weekly_summary_reminder, "cron", day_of_week="sun", hour=12, minute=0, args=[bot])
    sched.add_job(weekly_summary_reminder, "cron", day_of_week="sun", hour=21, minute=0, args=[bot])
    sched.add_job(monday_leaderboard, "cron", day_of_week="mon", hour=10, minute=0, args=[bot])
    return sched
