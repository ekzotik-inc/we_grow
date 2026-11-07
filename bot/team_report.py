"""«📸 Итоги команд»: картинка с результатами участников для каждой команды.

Админ-панель → «📸 Итоги команд» → превью себе → «📤 Отправить всем
командам». Каждая команда получает СВОЮ картинку (состав, баллы, место) и
подпись Stepy о том, почему командный зачёт важен (по правилам WE GROW
результат команды — среднее личных баллов участников).

Картинка рисуется Pillow в стиле Mini App (Sport Dark Glow): баннер
webapp/static/hero.jpg, метрики в строку, строки участников с полосами.
Шрифты Inter (OFL) лежат в assets/fonts — на сервере их может не быть.
"""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot import db
from bot.keyboards import open_app_kb
from bot.texts import fmt_points, stepy

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
HERO = ROOT / "webapp" / "static" / "hero.jpg"

W = 1080
BG = (11, 15, 23)
WHITE = (255, 255, 255)
NAME = (241, 245, 249)
MUTED = (100, 116, 139)
EMERALD = (52, 211, 153)
GOLD = (251, 191, 36)
MEDALS = [((253, 230, 138), (245, 158, 11)), ((241, 245, 249), (148, 163, 184)),
          ((255, 210, 168), (194, 110, 52))]


def _f(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def _plural(n: int, a: str, b: str, c: str) -> str:
    m, h = n % 10, n % 100
    return a if m == 1 and h != 11 else b if 2 <= m <= 4 and not 12 <= h <= 14 else c


def _grad(w: int, h: int, c1, c2, horizontal=True) -> Image.Image:
    g = Image.new("RGB", (w, h))
    px = g.load()
    n = max(1, (w if horizontal else h) - 1)
    for i in range(w if horizontal else h):
        t = i / n
        col = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        for j in range(h if horizontal else w):
            px[(i, j) if horizontal else (j, i)] = col
    return g


def _rounded(img: Image.Image, box, r: int, fill) -> None:
    ImageDraw.Draw(img).rounded_rectangle(box, r, fill=fill)


def _paste_rounded(base: Image.Image, src: Image.Image, xy, r: int) -> None:
    mask = Image.new("L", src.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *src.size), r, fill=255)
    base.paste(src, xy, mask)


def render(team: str, rank: int | None, total: int, points, full_days: int,
           members: list[dict]) -> bytes:
    rows = max(1, len(members))
    H = 770 + rows * 118 + 130
    img = Image.new("RGB", (W, H), BG)

    # Aurora-пятна
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-300, 300, 600, 1100), fill=(16, 120, 90))
    gd.ellipse((600, H - 700, 1400, H + 100), fill=(60, 62, 160))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(160)), 0.35)

    # Баннер с бегунами + затемнение
    if HERO.exists():
        hero = Image.open(HERO).convert("RGB")
        hero = hero.resize((W, int(hero.height * W / hero.width)))
        top = max(0, (hero.height - 470) // 2)
        hero = hero.crop((0, top, W, top + 470))
        grad = Image.new("L", (W, 470))
        gdr = ImageDraw.Draw(grad)
        for y in range(470):
            gdr.line((0, y, W, y), fill=int(100 + 155 * (y / 470) ** 1.4))
        img.paste(Image.composite(Image.new("RGB", (W, 470), BG), hero, grad), (0, 0))

    d = ImageDraw.Draw(img)
    d.text((64, 60), "STEP TOGETHER  ·  WE GROW", font=_f("Inter-SemiBold.otf", 26), fill=EMERALD)
    d.text((64, 250), "КОМАНДНЫЙ ЗАЧЁТ", font=_f("Inter-SemiBold.otf", 28), fill=EMERALD)
    d.text((64, 290), team, font=_f("InterDisplay-Black.otf", 92), fill=WHITE)
    place = f"Место {rank} из {total}" if rank else "Пока без рейтинга"
    d.text((66, 405), place, font=_f("Inter-Medium.otf", 34), fill=(148, 163, 184))

    # Карточка
    y0 = 500
    card = Image.new("RGB", (W - 96, H - y0 - 70), (20, 26, 36))
    _paste_rounded(img, card, (48, y0), 44)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((48, y0, W - 48, H - 70), 44, outline=(40, 48, 62), width=2)

    # Метрики в строку
    mx = [(fmt_points(points), "средний балл", EMERALD),
          (str(len(members)), _plural(len(members), "участник", "участника", "участников"), WHITE),
          (str(full_days), "дней 10K+\nвсей командой", GOLD)]
    cw = (W - 96) // 3
    for i, (v, lbl, col) in enumerate(mx):
        cx = 48 + cw * i + cw // 2
        fv = _f("InterDisplay-Black.otf", 72)
        d.text((cx, y0 + 70), v, font=fv, fill=col, anchor="mt")
        d.multiline_text((cx, y0 + 160), lbl, font=_f("Inter-Medium.otf", 24), fill=MUTED,
                         anchor="ma", align="center", spacing=4)
        if i:
            x = 48 + cw * i
            d.line((x, y0 + 60, x, y0 + 200), fill=(45, 54, 70), width=2)
    d.line((96, y0 + 240, W - 96, y0 + 240), fill=(40, 48, 62), width=2)

    # Участники
    y = y0 + 270
    mx_pts = max([float(m["points"] or 0) for m in members] + [1])
    if not members:
        d.text((W // 2, y + 30), "Пока никого", font=_f("Inter-Medium.otf", 32), fill=MUTED, anchor="mt")
    for i, m in enumerate(members):
        pts = float(m["points"] or 0)
        # бейдж места
        bx, by = 96, y + 14
        if i < 3:
            c1, c2 = MEDALS[i]
            badge = _grad(56, 56, c1, c2, horizontal=False)
            mask = Image.new("L", (56, 56), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 55, 55), fill=255)
            img.paste(badge, (bx, by), mask)
            numcol = (27, 20, 6)
        else:
            d.ellipse((bx, by, bx + 56, by + 56), fill=(38, 46, 60))
            numcol = (148, 163, 184)
        d = ImageDraw.Draw(img)
        d.text((bx + 28, by + 28), str(i + 1), font=_f("InterDisplay-Bold.otf", 28), fill=numcol, anchor="mm")
        # имя + очки
        name = m["name"] or "—"
        fn = _f("Inter-SemiBold.otf", 38)
        while d.textlength(name, font=fn) > 640 and len(name) > 3:
            name = name[:-2].rstrip() + "…" if not name.endswith("…") else name[:-2] + "…"
        d.text((180, y + 8), name, font=fn, fill=NAME)
        ptxt = fmt_points(m["points"] or 0)
        d.text((W - 150, y + 6), ptxt, font=_f("InterDisplay-Black.otf", 44), fill=EMERALD, anchor="ra")
        d.text((W - 96, y + 22), "pts", font=_f("Inter-Medium.otf", 24), fill=MUTED, anchor="ra")
        # полоса
        bw = W - 96 - 180
        d.rounded_rectangle((180, y + 70, 180 + bw, y + 80), 5, fill=(36, 44, 58))
        fw = int(bw * pts / mx_pts) if pts > 0 else 0
        if fw > 10:
            _paste_rounded(img, _grad(fw, 10, (16, 185, 129), (6, 182, 212)), (180, y + 70), 5)
        d = ImageDraw.Draw(img)
        if i < len(members) - 1:
            d.line((96, y + 108, W - 96, y + 108), fill=(32, 39, 52), width=2)
        y += 118

    d.text((W // 2, H - 40), "Результат команды = среднее личных баллов её участников",
           font=_f("Inter-Medium.otf", 24), fill=MUTED, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True, progressive=True)
    return buf.getvalue()


def caption(team: str, rank: int | None, total: int, points) -> str:
    place = f"<b>{rank} место из {total}</b>" if rank else "пока без места в рейтинге"
    return (
        f"🏆 <b>Командный зачёт: «{team}»</b>\n"
        f"Сейчас — {place}, средний балл команды <b>{fmt_points(points)}</b>. "
        f"На картинке — вклад каждого из вас 👆\n\n"
        + stepy(
            "Почему это так важно? По правилам WE GROW побеждает <b>команда</b>, а её "
            "результат — это <b>среднее</b> личных баллов всех участников. "
            "Значит, на итог одинаково влияет каждый: один пропущенный день тянет "
            "вниз всю команду, а твои 10 000+ шагов поднимают её вверх 🚀\n\n"
            "При равенстве баллов выше та команда, у которой больше дней, когда "
            "<b>все</b> прошли 10 000+. Так что поддерживайте друг друга и "
            "напоминайте сдать шаги до <b>23:55</b> 🤝"
        )
    )


async def build_all() -> list[dict]:
    """[{team_id, name, rank, total, points, png, caption}] по командам."""
    board = await db.team_leaderboard()
    total = len(board)
    out = []
    for rank, t in enumerate(board, 1):
        members = [{"name": m["full_name"], "points": m["points"]}
                   for m in await db.team_members(t["id"])]
        rk = rank if t["points"] else None
        png = await asyncio.to_thread(render, t["name"], rk, total, t["points"],
                                      int(t["full_days"] or 0), members)
        out.append({"team_id": t["id"], "name": t["name"], "rank": rk, "total": total,
                    "points": t["points"], "members": len(members), "png": png,
                    "caption": caption(t["name"], rk, total, t["points"])})
    return out


async def _send(bot: Bot, chat_id: int, photo, cap: str):
    try:
        return await bot.send_photo(chat_id, photo, caption=cap,
                                    reply_markup=open_app_kb("🌱 Мой личный прогресс"))
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await _send(bot, chat_id, photo, cap)
    except Exception as e:  # noqa: BLE001 — заблокировал бота и т.п.
        log.warning("team report to %s failed: %s", chat_id, e)
        return None


async def send_all(bot: Bot) -> tuple[int, int]:
    """Каждой команде — её картинка. Возвращает (команд, доставлено сообщений)."""
    teams_sent = delivered = 0
    for t in await build_all():
        ids = await db.team_member_ids([t["team_id"]])
        if not ids:
            continue
        fid = None
        for cid in ids:
            photo = fid or BufferedInputFile(t["png"], filename=f"team_{t['team_id']}.jpg")
            msg = await _send(bot, cid, photo, t["caption"])
            if msg is not None:
                delivered += 1
                if not fid and getattr(msg, "photo", None):
                    fid = msg.photo[-1].file_id
            await asyncio.sleep(0.05)
        teams_sent += 1
    return teams_sent, delivered
