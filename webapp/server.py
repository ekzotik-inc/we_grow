"""Backend Mini App: валидирует Telegram initData и отдаёт данные + статику.

Один веб-сервис: /api/* — данные, / — статичный фронтенд мини-аппа.
Переиспользует bot.db и bot.config. Запуск:
    uvicorn webapp.server:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.scoring import QUALIFYING_STEPS
from bot import db
from bot.config import config

MARATHON_START = config.marathon_start
MARATHON_END = config.marathon_end

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

    # Защита от replay: initData живёт не дольше суток (официальный алгоритм
    # требует проверять auth_date, иначе перехваченная строка валидна вечно).
    try:
        auth_ts = int(pairs.get("auth_date", "0"))
    except ValueError:
        auth_ts = 0
    if abs(time.time() - auth_ts) > 86400:
        raise HTTPException(status_code=401, detail="stale initData")

    try:
        user = json.loads(pairs["user"])
        return int(user["id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="no user")


# ---- Сессия по номеру телефона (fallback, когда initData недоступен) -------

TOKEN_TTL = 30 * 24 * 3600          # телефонная сессия живёт 30 дней


def _make_token(tg_id: int) -> str:
    """Подписанный токен сессии: telegram_id + срок жизни + HMAC на секрете
    бота. Подделать чужой токен без BOT_TOKEN нельзя, просроченный — невалиден."""
    expires = int(time.time()) + TOKEN_TTL
    payload = f"{tg_id}.{expires}"
    sig = hmac.new(config.bot_token.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str) -> int | None:
    try:
        tg_id_s, expires_s, sig = token.split(".", 2)
        expires = int(expires_s)
    except ValueError:
        return None                              # в т.ч. старый формат без TTL
    expected = hmac.new(config.bot_token.encode(),
                        f"{tg_id_s}.{expires_s}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig) or time.time() > expires:
        return None
    try:
        return int(tg_id_s)
    except ValueError:
        return None


# Rate limit входа по телефону: до 10 попыток за 10 минут с одного IP —
# защита от перебора чужих номеров. In-memory: процесс webapp один.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _login_allowed(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if now - t < 600]
    if len(attempts) >= 10:
        _LOGIN_ATTEMPTS[ip] = attempts
        return False
    attempts.append(now)
    _LOGIN_ATTEMPTS[ip] = attempts
    if len(_LOGIN_ATTEMPTS) > 10_000:            # не даём словарю расти вечно
        _LOGIN_ATTEMPTS.clear()
    return True


async def _auth(init_data: str | None, session: str | None = None) -> int:
    """Авторизация: приоритетно через Telegram initData, иначе — через
    подписанный токен сессии (вход по номеру телефона)."""
    if init_data:
        return _verify_init_data(init_data)
    if session:
        tg_id = _verify_token(session)
        if tg_id is not None:
            return tg_id
    raise HTTPException(status_code=401, detail="no auth")


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

@app.post("/api/login")
async def api_login(request: Request, phone: str = Body(..., embed=True)):
    """Вход по номеру телефона: сверяем с базой (участник должен быть
    зарегистрирован — с командой). Возвращаем токен сессии, если найден."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "?")
    if not _login_allowed(ip):
        return {"ok": False, "reason": "rate_limited"}
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 9:
        return {"ok": False, "reason": "bad_phone"}
    row = await db.find_by_phone(digits[-9:])          # сверяем по последним 9 цифрам
    if row is None:
        return {"ok": False, "registered": False}       # номер не в базе → на регистрацию
    if row["disqualified_at"] is not None:
        return {"ok": False, "reason": "disqualified"}
    return {"ok": True, "token": _make_token(row["telegram_id"])}


@app.get("/api/me")
async def api_me(x_init_data: str | None = Header(default=None),
                 x_session: str | None = Header(default=None)):
    tg_id = await _auth(x_init_data, x_session)
    card = await db.participant_card(tg_id)
    if card is None or card["team_id"] is None or card["disqualified_at"] is not None \
            or card["approved_at"] is None:
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
async def api_team(x_init_data: str | None = Header(default=None),
                   x_session: str | None = Header(default=None)):
    tg_id = await _auth(x_init_data, x_session)
    card = await db.participant_card(tg_id)
    if card is None or card["team_id"] is None or card["disqualified_at"] is not None \
            or card["approved_at"] is None:
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
async def api_leaderboard(x_init_data: str | None = Header(default=None),
                          x_session: str | None = Header(default=None)):
    await _auth(x_init_data, x_session)
    teams = await db.team_leaderboard()
    top = await db.top_participants(10)
    return {
        "teams": [{"name": t["name"], "points": t["points"]} for t in teams],
        "top": [{"name": p["full_name"] or "—", "points": p["points"]} for p in top],
    }


async def _serve_screenshot(file_id: str):
    """Скачивает файл у Telegram на сервере и отдаёт как изображение —
    токен бота наружу не попадает."""
    import aiohttp
    from fastapi.responses import Response

    if file_id.startswith("doc:"):          # скрин, присланный файлом
        file_id = file_id[4:]

    api = f"https://api.telegram.org/bot{config.bot_token}"
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{api}/getFile", params={"file_id": file_id},
                         timeout=aiohttp.ClientTimeout(total=20)) as r:
            meta = await r.json()
        if not meta.get("ok"):
            raise HTTPException(status_code=404, detail="file expired")
        path = meta["result"]["file_path"]
        async with s.get(f"https://api.telegram.org/file/bot{config.bot_token}/{path}",
                         timeout=aiohttp.ClientTimeout(total=30)) as r:
            data = await r.read()
    ext = path.rsplit(".", 1)[-1].lower()
    media = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return Response(content=data, media_type=media,
                    headers={"Cache-Control": "private, max-age=3600"})


@app.get("/shot/{entry_id}/{sig}")
async def api_screenshot(entry_id: int, sig: str):
    """Дневной скриншот по подписанной ссылке (для выгрузки Excel)."""
    from bot.export import shot_sig
    if not hmac.compare_digest(shot_sig(entry_id), sig):
        raise HTTPException(status_code=403, detail="bad signature")
    entry = await db.entry_by_id(entry_id)
    if entry is None or not entry["screenshot_file_id"]:
        raise HTTPException(status_code=404, detail="no screenshot")
    return await _serve_screenshot(entry["screenshot_file_id"])


@app.get("/wshot/{ws_id}/{sig}")
async def api_weekly_screenshot(ws_id: int, sig: str):
    """Скриншот еженедельного отчёта по подписанной ссылке (для Excel)."""
    from bot.export import shot_sig
    if not hmac.compare_digest(shot_sig(ws_id, "wshot"), sig):
        raise HTTPException(status_code=403, detail="bad signature")
    row = await db.weekly_summary_by_id(ws_id)
    if row is None or not row["screenshot_file_id"]:
        raise HTTPException(status_code=404, detail="no screenshot")
    return await _serve_screenshot(row["screenshot_file_id"])


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/", StaticFiles(directory=_STATIC), name="static")
