"""🏁 Финал марафона: объявление победителя + личный итог каждому участнику.

Раньше после последнего дня бот просто замолкал: все рассылки работают только
в даты марафона. Теперь:

* 09:05 на следующий день после финиша (и ещё 2 дня, пока итоги не
  объявлены) — напоминание админам: «марафон завершён, на проверке N →
  🏁 Финал марафона». Автоматически участникам ничего не уходит: последние
  результаты и недельные отчёты ещё модерируются, победителя объявляет P&C.
* Админ-панель → «🏁 Финал марафона»: таблица, сколько заявок ещё на
  проверке, превью личного итога себе, затем «📣 Объявить итоги» с
  подтверждением. Повторно разослать нельзя (флаг final_sent в settings).
* Каждый участник получает СВОЮ картинку «Мой марафон» (шаги, баллы, дни,
  лучший день, лучшая серия, место команды) и подпись с победителем; у
  команды-чемпиона — поздравление и призы.

Картинка рисуется Pillow в стиле «📸 Итогов команд» (bot/team_report.py).
"""
from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw, ImageFilter

from backend.scoring import best_streak
from bot import db, settings
from bot.config import config
from bot.keyboards import open_app_kb
from bot.team_report import (BG, EMERALD, GOLD, HERO, MUTED, WHITE, _f, _grad,
                             _paste_rounded, _plural)
from bot.texts import PRIZES_LINE, fmt_points, marathon_dates, stepy

log = logging.getLogger(__name__)

SENT_KEY = "final_sent"          # ISO-время рассылки итогов
WINNER_KEY = "final_winner"      # название команды-победителя (для Mini App)
REMIND_DAYS = 3                  # сколько дней после финиша напоминать админам


@dataclass(frozen=True)
class Personal:
    tg_id: int
    name: str
    team: str
    team_rank: int | None
    teams_total: int
    points: float
    steps: int
    days: int
    best_day: int
    best_streak: int
    champion: bool


@dataclass(frozen=True)
class Standings:
    board: list[dict]
    winner: dict | None
    pending: int


def is_finished(today: date | None = None) -> bool:
    today = today or datetime.now(config.tz).date()
    return today > config.marathon_end


def marathon_days() -> int:
    return (config.marathon_end - config.marathon_start).days + 1


async def standings() -> Standings:
    board = await db.team_leaderboard()
    winner = board[0] if board and float(board[0]["points"] or 0) > 0 else None
    return Standings(board, winner, await db.pending_submissions_count())


async def personals(st: Standings) -> list[Personal]:
    rank = {t["id"]: i for i, t in enumerate(st.board, 1)}
    days = await db.final_qualifying_days()
    win_id = st.winner["id"] if st.winner else None
    return [Personal(
        tg_id=r["telegram_id"], name=(r["full_name"] or "—").strip(), team=r["team_name"],
        team_rank=rank.get(r["team_id"]), teams_total=len(st.board),
        points=float(r["points"] or 0), steps=int(r["steps"] or 0), days=int(r["days"] or 0),
        best_day=int(r["best_day"] or 0), best_streak=best_streak(days.get(r["telegram_id"], {})),
        champion=r["team_id"] == win_id,
    ) for r in await db.final_rows()]


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _fit(d: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    while d.textlength(text, font=font) > width and len(text) > 3:
        text = text[:-2].rstrip() + "…"
    return text


def render(p: Personal) -> bytes:
    """Картинка «Мой марафон» 1080×1350 (формат поста 4:5)."""
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), BG)

    if HERO.exists():
        hero = Image.open(HERO).convert("RGB")
        hero = hero.resize((W, int(hero.height * W / hero.width)))
        top = max(0, (hero.height - 430) // 2)
        hero = hero.crop((0, top, W, top + 430))
        mask = Image.new("L", (W, 430))
        md = ImageDraw.Draw(mask)
        for y in range(430):
            md.line((0, y, W, y), fill=int(90 + 165 * (y / 430) ** 1.3))
        img.paste(Image.composite(Image.new("RGB", (W, 430), BG), hero, mask), (0, 0))
    # Свечение — ПОСЛЕ баннера, иначе на его нижней кромке виден шов.
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-320, 380, 560, 1200), fill=(16, 120, 90))
    gd.ellipse((620, 760, 1420, 1560), fill=(60, 62, 160))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(170)), 0.35)

    d = ImageDraw.Draw(img)
    d.text((64, 60), "STEP TOGETHER  ·  WE GROW", font=_f("Inter-SemiBold.otf", 26), fill=EMERALD)
    d.text((64, 232), "МОЙ МАРАФОН", font=_f("Inter-SemiBold.otf", 28), fill=EMERALD)
    fn = _f("InterDisplay-Black.otf", 76)
    d.text((64, 270), _fit(d, p.name, fn, W - 128), font=fn, fill=WHITE)
    place = (f"Команда «{p.team}» · {p.team_rank} место из {p.teams_total}"
             if p.team_rank else f"Команда «{p.team}»")
    fm = _f("Inter-Medium.otf", 32)
    d.text((66, 368), _fit(d, place, fm, W - 132), font=fm, fill=(148, 163, 184))

    y0 = 440 if p.champion else 480      # без плашки — чуть ниже, чтобы не было дыры внизу
    if p.champion:
        lbl = "КОМАНДА-ЧЕМПИОН"
        fb = _f("InterDisplay-Bold.otf", 28)
        w = int(d.textlength(lbl, font=fb)) + 64
        _paste_rounded(img, _grad(w, 54, (253, 230, 138), (245, 158, 11)), (64, y0), 27)
        d = ImageDraw.Draw(img)
        d.text((64 + w // 2, y0 + 27), lbl, font=fb, fill=(27, 20, 6), anchor="mm")
        y0 += 78

    # Главная цифра — шаги
    d.text((64, y0 + 10), _num(p.steps), font=_f("InterDisplay-Black.otf", 150), fill=WHITE)
    d.text((70, y0 + 190), "шагов за марафон", font=_f("Inter-Medium.otf", 34), fill=MUTED)

    # Плитки 2×2
    tiles = [
        (fmt_points(p.points), _plural(int(p.points), "балл", "балла", "баллов"), EMERALD),
        (f"{p.days}/{marathon_days()}", "дней сдано", WHITE),
        (_num(p.best_day), "лучший день, шагов", GOLD),
        (str(p.best_streak), "лучшая серия 10K+, " + _plural(p.best_streak, "день", "дня", "дней"),
         (251, 146, 60)),
    ]
    ty = y0 + 270
    tw, th, gap = (W - 128 - 24) // 2, 170, 24
    for i, (v, lbl, col) in enumerate(tiles):
        x = 64 + (i % 2) * (tw + gap)
        y = ty + (i // 2) * (th + gap)
        _paste_rounded(img, Image.new("RGB", (tw, th), (20, 26, 36)), (x, y), 32)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x, y, x + tw, y + th), 32, outline=(40, 48, 62), width=2)
        d.text((x + 32, y + 28), v, font=_f("InterDisplay-Black.otf", 64), fill=col)
        d.text((x + 34, y + 114), lbl, font=_f("Inter-Medium.otf", 26), fill=MUTED)

    d.text((W // 2, H - 92), "Спасибо, что шагали вместе!", font=_f("Inter-SemiBold.otf", 34),
           fill=WHITE, anchor="mm")
    d.text((W // 2, H - 46), f"Марафон шагов · {marathon_dates()}", font=_f("Inter-Medium.otf", 26),
           fill=MUTED, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True, progressive=True)
    return buf.getvalue()


def caption(p: Personal, st: Standings) -> str:
    w = st.winner
    head = "🏁 <b>Марафон WE GROW завершён!</b>\n"
    if w:
        head += (f"🏆 Победитель — команда <b>«{w['name']}»</b> "
                 f"(средний балл <b>{fmt_points(w['points'])}</b>).\n")
    if p.champion:
        body = ("🎉 <b>Это твоя команда!</b> Поздравляем — вы лучшие.\n"
                f"{PRIZES_LINE}. О вручении сообщит P&C.\n\n")
        say = ("Вы сделали это вместе: каждый день, каждый шаг. Горжусь вами! "
               "Наденьте наушники, включите колонку — и празднуйте 🎶")
    else:
        place = (f"{p.team_rank} место из {p.teams_total}" if p.team_rank else "без места")
        body = f"Твоя команда «{p.team}» — <b>{place}</b>.\n\n"
        say = ("Спасибо, что шагал(а) вместе с нами! Две недели движения — это "
               "уже победа над диваном 💪 Не теряй темп: 10 000 шагов в день "
               "отлично работают и без марафона 🌱")
    return (head + body + "На картинке — твой марафон в цифрах 👆\n\n" + stepy(say))[:1024]


async def _send_photo(bot: Bot, chat_id: int, photo, cap: str):
    try:
        return await bot.send_photo(chat_id, photo, caption=cap,
                                    reply_markup=open_app_kb("🌱 Открыть итоги"))
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await _send_photo(bot, chat_id, photo, cap)
    except Exception as e:  # noqa: BLE001 — заблокировал бота и т.п.
        log.info("final to %s failed: %s", chat_id, e)
        return None


async def preview(bot: Bot, admin_id: int) -> str | None:
    """Пример итога админу: его собственный (если он участник) или первый в списке."""
    st = await standings()
    people = await personals(st)
    if not people:
        return None
    p = next((x for x in people if x.tg_id == admin_id), people[0])
    png = await asyncio.to_thread(render, p)
    await bot.send_photo(admin_id, BufferedInputFile(png, filename="final.jpg"),
                         caption=caption(p, st), reply_markup=open_app_kb("🌱 Открыть итоги"))
    return p.name


async def send_all(bot: Bot) -> tuple[int, int]:
    """Разослать итоги всем активным участникам. (получателей, доставлено)."""
    st = await standings()
    people = await personals(st)
    delivered = 0
    for p in people:
        png = await asyncio.to_thread(render, p)
        if await _send_photo(bot, p.tg_id, BufferedInputFile(png, filename="final.jpg"),
                             caption(p, st)):
            delivered += 1
        await asyncio.sleep(0.06)          # ~15 сообщений/с — ниже лимитов Telegram
    return len(people), delivered


async def claim_send(winner: str | None) -> bool:
    """Отметить «итоги отправлены»; False — уже отправлены (двойное нажатие,
    два админа сразу). Флаг ставится ДО рассылки."""
    await settings.load()
    if settings.get(SENT_KEY):
        return False
    await settings.set(SENT_KEY, datetime.now(config.tz).isoformat(timespec="minutes"))
    await settings.set(WINNER_KEY, winner or "")
    return True


async def remind_admins(bot: Bot) -> None:
    """09:05 после финиша — напомнить админам объявить итоги (до REMIND_DAYS дней)."""
    today = datetime.now(config.tz).date()
    if not (0 < (today - config.marathon_end).days <= REMIND_DAYS) or settings.get(SENT_KEY):
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from bot import notify
    pending = await db.pending_submissions_count()
    tail = (f"⏳ На проверке ещё <b>{pending}</b> — сначала проверьте их, от них зависит "
            "итоговая таблица." if pending else "✅ Все заявки проверены.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏁 Финал марафона", callback_data="adm:final")]])
    await notify.notify_admins(
        bot, "🏁 <b>Марафон завершён!</b>\n" + tail +
        "\n\nКогда будете готовы — объявите итоги: каждый участник получит свою "
        "картинку «Мой марафон» и имя команды-победителя.", reply_markup=kb)
