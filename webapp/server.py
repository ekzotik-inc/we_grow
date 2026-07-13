"""Backend Mini App: валидирует Telegram initData и отдаёт данные + статику.

Один веб-сервис: /api/* — данные, / — статичный фронтенд мини-аппа.
Переиспользует bot.db и bot.config. Запуск:
    uvicorn webapp.server:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.scoring import QUALIFYING_STEPS
from bot import db
from bot.config import config

MARATHON_START = date(2026, 7, 17)
MARATHON_END = date(2026, 8, 7)

_STATIC = Path(__file__).with_name("static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate()
    await db.connect(config.database_url)
    yield
    await db.close()


app = FastAPI(title="Step Together Mini App", lifespan=lifespan)


# ---- Авторизация через Telegram initData ---------------------------------

def _verify_init_data(init_data: str) -> int:
    """Проверяет подпись initData и возвращает telegram_id пользователя."""
    if not init_data:
        raise HTTPException(status_code=401, detail="no initData")
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        raise HTTPException(status_code=401, detail="bad initData")
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="no hash")

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", config.bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        user = json.loads(pairs["user"])
        return int(user["id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="no user")


async def _auth(init_data: str | None) -> int:
    return _verify_init_data(init_data or "")


# ---- Вспомогательное -----------------------------------------------------

def _best_streak(steps_by_date: dict[date, int]) -> int:
    best = cur = 0
    prev: date | None = None
    for d in sorted(steps_by_date):
        if steps_by_date[d] >= QUALIFYING_STEPS:
            cur = cur + 1 if (prev and (d - prev).days == 1) else 1
            best = max(best, cur)
        else:
            cur = 0
        prev = d
    return best


# ---- API -----------------------------------------------------------------

@app.get("/api/me")
async def api_me(x_init_data: str | None = Header(default=None)):
    tg_id = await _auth(x_init_data)
    card = await db.participant_card(tg_id)
    if card is None or card["team_id"] is None:
        return {"registered": False}

    entries = await db.entries_list(tg_id)
    steps_by_date = {e["entry_date"]: e["steps"] for e in entries}
    points_by_date = {e["entry_date"]: e["points"] for e in entries}
    status_by_date = {e["entry_date"]: e["status"] for e in entries}
    # серию считаем только по принятым дням
    accepted_steps = {e["entry_date"]: e["steps"] for e in entries if e["status"] == "accepted"}
    today = datetime.now(config.tz).date()
    streak = await db.get_streak(tg_id)

    calendar = []
    d = MARATHON_START
    while d <= MARATHON_END:
        calendar.append({
            "date": d.isoformat(),
            "steps": steps_by_date.get(d, 0),
            "points": points_by_date.get(d, 0),
            "status": status_by_date.get(d),          # accepted | pending | rejected | None
            "is_today": d == today,
            "future": d > today,
        })
        d = d.fromordinal(d.toordinal() + 1)

    return {
        "registered": True,
        "full_name": card["full_name"],
        "team_name": card["team_name"],
        "total_points": await db.total_points(tg_id),
        "today_status": status_by_date.get(today),    # для плитки «Сегодня»
        "current_streak": streak.current_len,
        "best_streak": _best_streak(accepted_steps),
        "calendar": calendar,
        "marathon": {"start": MARATHON_START.isoformat(), "end": MARATHON_END.isoformat()},
    }


@app.get("/api/team")
async def api_team(x_init_data: str | None = Header(default=None)):
    tg_id = await _auth(x_init_data)
    card = await db.participant_card(tg_id)
    if card is None or card["team_id"] is None:
        return {"registered": False}

    members = await db.team_members(card["team_id"])
    board = await db.team_leaderboard()
    rank = next((i for i, t in enumerate(board, 1) if t["name"] == card["team_name"]), None)
    return {
        "registered": True,
        "team_name": card["team_name"],
        "rank": rank,
        "teams_count": len(board),
        "total_points": sum(m["points"] for m in members),
        "members": [{"name": m["full_name"] or "—", "points": m["points"]} for m in members],
    }


@app.get("/api/leaderboard")
async def api_leaderboard(x_init_data: str | None = Header(default=None)):
    await _auth(x_init_data)
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    return {
        "teams": [{"name": t["name"], "points": t["points"]} for t in teams],
        "top": [{"name": p["full_name"] or "—", "points": p["points"]} for p in top],
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/", StaticFiles(directory=_STATIC), name="static")
