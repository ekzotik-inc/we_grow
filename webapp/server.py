"""Backend Mini App: валидирует Telegram initData и отдаёт данные + статику.

Один веб-сервис: /api/* — данные, / — статичный фронтенд мини-аппа.
Переиспользует bot.db и bot.config. Запуск:
    uvicorn webapp.server:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.scoring import best_streak
from bot import db
from bot.config import config

MARATHON_START = config.marathon_start
MARATHON_END = config.marathon_end

_STATIC = Path(__file__).with_name("static")


_tg_bot = None          # aiogram Bot только для отправки (пуши после модерации)


def _owner_ids() -> set[int]:
    """Владельцы для алертов: у webapp нет своей ADMIN_IDS — берём копию,
    которую публикует бот (env_admins), + назначенных владельцев."""
    from bot import settings
    env = {int(x) for x in (settings.get("env_admins") or "").split(",") if x.strip().isdigit()}
    return env | settings.owner_ids()


async def _settings_refresher() -> None:
    """Кэш настроек (админы, эмодзи, URL) — раз в минуту из БД."""
    from bot import settings
    while True:
        await asyncio.sleep(60)
        try:
            await settings.load()
        except Exception as e:  # noqa: BLE001 — БД моргнула, попробуем через минуту
            _log.warning("settings refresh: %s", e)


async def _setup_bot() -> None:
    """Бот для пушей из админки Mini App — с теми же премиум-эмодзи, что у бота."""
    global _tg_bot
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from bot import premium_emoji, settings
    from bot.premium_emoji import EmojiMiddleware
    _tg_bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    _tg_bot.session.middleware(EmojiMiddleware())
    if not premium_emoji.ENABLED:
        return
    try:
        await premium_emoji.validate(_tg_bot)
        saved = settings.get("emoji_pack")
        if saved:
            premium_emoji.apply_pack(json.loads(saved))
    except Exception as e:  # noqa: BLE001 — без премиум-эмодзи пуши всё равно уйдут
        _log.warning("premium emoji in webapp: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate()
    await db.connect(config.database_url)
    from bot import alerts, settings
    await settings.load()
    alerts.install(config.bot_token, _owner_ids, "Mini App")
    refresher = asyncio.create_task(_settings_refresher())
    await _setup_bot()
    yield
    refresher.cancel()
    if _tg_bot is not None:
        await _tg_bot.session.close()
    if _http is not None and not _http.closed:
        await _http.close()
    await db.close()


app = FastAPI(title="Step Together Mini App", lifespan=lifespan)
# index.html ~170 КБ → ~40 КБ по сети: на мобильном интернете это главная
# задержка первого открытия. JSON API тоже сжимается.
app.add_middleware(GZipMiddleware, minimum_size=1024)

import logging  # noqa: E402

_log = logging.getLogger("webapp")


@app.middleware("http")
async def _timing(request: Request, call_next):
    """Медленные запросы — в лог Render: сразу видно, что тормозит Mini App."""
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    if ms > 500:
        _log.warning("медленный запрос %s %s: %.0f мс", request.method, request.url.path, ms)
    response.headers["Server-Timing"] = f"app;dur={ms:.0f}"
    return response


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

async def _is_admin(tg_id: int) -> bool:
    """Админ = env ADMIN_IDS (своя или опубликованная ботом) + доп-админы из settings (как settings.is_admin
    в боте; кеша настроек у webapp нет — читаем ключ напрямую)."""
    if tg_id in config.admin_ids:
        return True
    # env_admins — копия ADMIN_IDS сервиса бота (у webapp своей env нет),
    # extra_admins — назначенные через бот.
    rows = await db.pool().fetch(
        "SELECT value FROM settings WHERE key IN ('extra_admins','env_admins')")
    ids = {x.strip() for r in rows for x in (r["value"] or "").split(",") if x.strip()}
    return str(tg_id) in ids


# Командный рейтинг одинаков для всех, а после пуша Mini App открывают
# десятки людей разом. Держим результат несколько секунд и делим один
# запрос между одновременными вызовами (задача, а не значение).
_BOARD_TTL = 8.0
_board: tuple[float, asyncio.Task] | None = None


async def _leaderboard() -> list[dict]:
    global _board
    now = time.monotonic()
    if _board is None or now - _board[0] > _BOARD_TTL or \
            (_board[1].done() and _board[1].exception() is not None):
        _board = (now, asyncio.ensure_future(db.team_leaderboard()))
    return await asyncio.shield(_board[1])


def _marathon() -> dict:
    return {"start": MARATHON_START.isoformat(), "end": MARATHON_END.isoformat()}


async def _admin_view() -> dict:
    """«Прогресс» для админа без анкеты: тот же экран, что у участника, но
    по ВСЕМ активным участникам (подтверждён, не DQ) — суммы за каждый день."""
    q_days = db.pool().fetch(
        """SELECT d.entry_date,
                  sum(d.steps) FILTER (WHERE d.status='accepted') AS acc_steps,
                  sum(d.points) FILTER (WHERE d.status='accepted') AS acc_points,
                  count(*) FILTER (WHERE d.status='accepted') AS n_acc,
                  count(*) FILTER (WHERE d.status='pending') AS n_pend,
                  count(*) FILTER (WHERE d.status='rejected') AS n_rej,
                  sum(d.steps) AS all_steps
             FROM daily_entries d JOIN participants p ON p.telegram_id=d.participant_id
            WHERE p.approved_at IS NOT NULL AND p.disqualified_at IS NULL
            GROUP BY d.entry_date""")
    q_bonus = db.pool().fetchval(
        """SELECT COALESCE(sum(w.bonus_points),0) FROM weekly_summaries w
             JOIN participants p ON p.telegram_id=w.participant_id
            WHERE p.approved_at IS NOT NULL AND p.disqualified_at IS NULL""")
    q_active = db.pool().fetchval(
        """SELECT count(*) FROM participants WHERE team_id IS NOT NULL
              AND approved_at IS NOT NULL AND disqualified_at IS NULL""")
    q_streak = db.pool().fetchval(
        """SELECT COALESCE(max(s.current_len),0) FROM streaks s
             JOIN participants p ON p.telegram_id=s.participant_id
            WHERE p.approved_at IS NOT NULL AND p.disqualified_at IS NULL""")
    # Пять независимых запросов — параллельно (раньше шли по очереди).
    rows, bonus, active, streak, board = await asyncio.gather(
        q_days, q_bonus, q_active, q_streak, _leaderboard())
    by = {r["entry_date"]: r for r in rows}
    leader = ({"name": board[0]["name"], "points": board[0]["points"]}
              if board and board[0]["points"] else None)
    today = datetime.now(config.tz).date()
    calendar, d, total = [], MARATHON_START, 0
    while d <= MARATHON_END:
        r = by.get(d)
        status = None
        if r:
            status = ("pending" if r["n_pend"] else "accepted" if r["n_acc"]
                      else "rejected" if r["n_rej"] else None)
        pts = int(r["acc_points"] or 0) if r else 0
        total += pts
        calendar.append({
            "date": d.isoformat(),
            "steps": int((r["acc_steps"] if r and r["n_acc"] else r["all_steps"]) or 0) if r else 0,
            "points": pts, "status": status,
            "accepted": int(r["n_acc"]) if r else 0,
            "pending": int(r["n_pend"]) if r else 0,
            "is_today": d == today, "future": d > today,
        })
        d = d.fromordinal(d.toordinal() + 1)
    return {
        "registered": True, "admin": True, "aggregate": True,
        "full_name": "Все участники", "team_name": None,
        "participants": int(active or 0),
        "total_points": total + int(bonus or 0),
        "hour": datetime.now(config.tz).hour,
        "today_status": next((c["status"] for c in calendar if c["is_today"]), None),
        "current_streak": int(streak or 0), "best_streak": int(streak or 0),
        "calendar": calendar, "marathon": _marathon(), "leader": leader,
    }

_best_streak = best_streak      # общая чистая функция, покрыта тестами


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
        if await _is_admin(tg_id):
            return await _admin_view()
        return {"registered": False}

    # Записи, сводка и флаг админа не зависят друг от друга — параллельно.
    entries, summary, is_admin = await asyncio.gather(
        db.entries_list(tg_id), db.participant_summary(tg_id), _is_admin(tg_id))
    summary = summary or {}
    steps_by_date = {e["entry_date"]: e["steps"] for e in entries}
    points_by_date = {e["entry_date"]: e["points"] for e in entries}
    status_by_date = {e["entry_date"]: e["status"] for e in entries}
    # серию считаем только по принятым дням
    accepted_steps = {e["entry_date"]: e["steps"] for e in entries if e["status"] == "accepted"}
    today = datetime.now(config.tz).date()
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

    # Личное место, баллы и живая серия — одним запросом (как в главном меню
    # бота), без командного рейтинга: на экране «Прогресс» он не нужен.
    return {
        "registered": True,
        "admin": is_admin,          # показать вкладку «Админка»
        "full_name": card["full_name"],
        "team_name": card["team_name"],
        "total_points": int(summary.get("points") or 0),
        # Место КОМАНДЫ — личного рейтинга в WE GROW нет.
        "team_rank": summary.get("team_rank"),
        "teams_total": summary.get("teams_total"),
        # Час по таймзоне марафона — для приветствия. Часы клиента не годятся:
        # у участника западнее Бишкека «вечер» наступил бы не тогда.
        "hour": datetime.now(config.tz).hour,
        "today_status": status_by_date.get(today),    # для плитки «Сегодня»
        "current_streak": summary.get("streak", 0),
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
        if not await _is_admin(tg_id):
            return {"registered": False}
        # Админ без анкеты: все команды с составом.
        board, by_team = await asyncio.gather(_leaderboard(), db.members_by_team())
        return {"registered": False, "admin": True, "teams": [
            {"name": t["name"], "points": t["points"], "full_days": t["full_days"],
             "members": [{"name": m["full_name"] or "—", "points": m["points"]}
                         for m in by_team.get(t["id"], [])]}
            for t in board]}

    members, board = await asyncio.gather(db.team_members(card["team_id"]), _leaderboard())
    rank = next((i for i, t in enumerate(board, 1) if t["name"] == card["team_name"]), None)
    mine = board[rank - 1] if rank else {}
    return {
        "registered": True,
        "team_name": card["team_name"],
        "rank": rank,
        "teams_count": len(board),
        # Командный результат WE GROW — среднее личных баллов (+ очки флешмобов).
        "total_points": mine.get("points", 0),
        "full_days": mine.get("full_days", 0),
        "members": [{"name": m["full_name"] or "—", "points": m["points"]} for m in members],
    }


@app.get("/api/leaderboard")
async def api_leaderboard(x_init_data: str | None = Header(default=None),
                          x_session: str | None = Header(default=None)):
    await _auth(x_init_data, x_session)
    # Только командный зачёт: личного топа в WE GROW нет.
    teams = await _leaderboard()
    return {
        "teams": [{"name": t["name"], "points": t["points"],
                   "members": t["members"], "full_days": t["full_days"]} for t in teams],
        "final": _final_state(),
    }


def _final_state() -> dict:
    """Фаза финала для Mini App: марафон завершён? итоги объявлены? победитель —
    только после объявления P&C (до этого идёт проверка последних результатов)."""
    from bot import settings
    from bot.final import SENT_KEY, WINNER_KEY
    finished = datetime.now(config.tz).date() > MARATHON_END
    announced = bool(settings.get(SENT_KEY))
    return {"finished": finished, "announced": announced,
            "winner": (settings.get(WINNER_KEY) or None) if announced else None}


# ---- Админка Mini App (только просмотр) -----------------------------------
# Все действия (модерация, ручной ввод, отмена) остаются в боте: там пересчёт
# серий/бонусов/флешмобов и пуши участникам. Здесь — только чтение.

ADMIN_LIST_LIMIT = 500          # участников в списке админки
ADMIN_QUEUE_LIMIT = 100         # заявок в очереди модерации
SILENT_DAYS = 2                 # «молчит» — нет результатов N+ дней


async def _require_admin(init_data: str | None, session: str | None) -> int:
    tg_id = await _auth(init_data, session)
    if not await _is_admin(tg_id):
        raise HTTPException(status_code=403, detail="admins only")
    return tg_id


def _shot_link(entry_id: int, file_id: str | None) -> str | None:
    if not file_id:
        return None
    from bot.export import shot_sig
    return f"/shot/{entry_id}/{shot_sig(entry_id)}"


def _iso(v) -> str | None:
    return v.isoformat() if v is not None else None


@app.get("/api/admin/overview")
async def api_admin_overview(x_init_data: str | None = Header(default=None),
                             x_session: str | None = Header(default=None)):
    """Сводка P&C: сегодня, очередь, молчуны, активности дня, динамика по дням."""
    await _require_admin(x_init_data, x_session)
    today = datetime.now(config.tz).date()
    st = await db.digest_stats(today)
    counts = await db.status_counts()
    days = await db.pool().fetch(
        """SELECT d.entry_date,
                  count(*) FILTER (WHERE d.status='accepted') AS accepted,
                  count(*) FILTER (WHERE d.status='pending')  AS pending,
                  count(*) FILTER (WHERE d.status='rejected') AS rejected
             FROM daily_entries d JOIN participants p ON p.telegram_id=d.participant_id
            WHERE p.approved_at IS NOT NULL AND p.disqualified_at IS NULL
              AND d.entry_date BETWEEN $1 AND $2
            GROUP BY d.entry_date ORDER BY d.entry_date""",
        MARATHON_START, min(today, MARATHON_END))
    ch = await db.challenge_for(today)
    fm = await db.flashmob_for(today)
    return {
        "today": today.isoformat(), "marathon": _marathon(),
        "active": int(st["active"] or 0),
        "submitted": int(st["total"] or 0), "accepted": int(st["accepted"] or 0),
        "pending_today": int(st["pending"] or 0), "rejected": int(st["rejected"] or 0),
        "queue": await db.pending_submissions_count(),
        "registrations": int(counts.get("pending") or 0),
        "disqualified": int(counts.get("disq") or 0),
        "silent": [{"name": r["full_name"] or "—", "team": r["team_name"],
                    "last": _iso(r["last_entry"])} for r in st["silent"]],
        "days": [{"date": r["entry_date"].isoformat(), "accepted": int(r["accepted"]),
                  "pending": int(r["pending"]), "rejected": int(r["rejected"])} for r in days],
        "challenge": ({"multiplier": ch["multiplier"],
                       "after": ch["after_time"].strftime("%H:%M") if ch["after_time"] else None,
                       "teams": len(ch["team_ids"] or [])} if ch else None),
        "flashmob": ({"pct": fm["threshold_pct"], "min_steps": fm["min_steps"],
                      "bonus": fm["bonus_points"], "teams": len(fm["team_ids"] or [])}
                     if fm else None),
    }


@app.get("/api/admin/queue")
async def api_admin_queue(x_init_data: str | None = Header(default=None),
                          x_session: str | None = Header(default=None)):
    """Очередь модерации (результаты на проверке) и заявки на регистрацию."""
    await _require_admin(x_init_data, x_session)
    from backend.scoring import REVIEW_STEPS
    subs = await db.pending_submissions(ADMIN_QUEUE_LIMIT)
    regs = await db.pending_participants()
    return {
        "total": await db.pending_submissions_count(),
        "entries": [{"id": r["id"], "tg_id": r["participant_id"],
                     "name": r["full_name"] or "—", "team": r["team_name"],
                     "date": r["entry_date"].isoformat(), "steps": r["steps"],
                     "big": r["steps"] > REVIEW_STEPS,
                     "shot": _shot_link(r["id"], r["screenshot_file_id"])} for r in subs],
        "registrations": [{"tg_id": r["telegram_id"], "name": r["full_name"] or "—",
                           "username": r["username"], "team": r["team_name"],
                           "created": _iso(r["created_at"])} for r in regs],
    }


_MOD_ACTIONS = {"accept", "reject"}


@app.post("/api/admin/moderate")
async def api_admin_moderate(request: Request, x_init_data: str | None = Header(default=None),
                             x_session: str | None = Header(default=None)):
    """Принять / отклонить результат из Mini App — та же логика, что у кнопок
    в канале проверки (bot/moderation.py): серия, бонус, флешмоб, пуши.
    Карточка в канале после решения теряет кнопки и получает подпись."""
    admin_id = await _require_admin(x_init_data, x_session)
    try:
        body = await request.json()
        entry_id, action = int(body["entry_id"]), str(body["action"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="bad request")
    if action not in _MOD_ACTIONS:
        raise HTTPException(status_code=400, detail="bad action")
    if _tg_bot is None:
        raise HTTPException(status_code=503, detail="bot not ready")
    from bot import moderation
    res = await (moderation.accept if action == "accept" else moderation.reject)(_tg_bot, entry_id)
    if res.ok:
        me = await db.get_participant(admin_id)
        who = ((me["full_name"] or "").split() or ["P&C"])[0] if me else "P&C"
        await moderation.close_review_card(_tg_bot, entry_id, res, who)
        _log.info("модерация из Mini App: %s #%s → %s", admin_id, entry_id, res.code)
    return {"ok": res.ok, "code": res.code, "message": res.message,
            "points": res.points, "mult": res.mult,
            "left": await db.pending_submissions_count()}


@app.get("/api/admin/participants")
async def api_admin_participants(q: str = "", x_init_data: str | None = Header(default=None),
                                 x_session: str | None = Header(default=None)):
    """Все участники с анкетой: баллы, шаги, дни, последняя сдача. Поиск по
    ФИО / @username / ID / последним цифрам телефона."""
    await _require_admin(x_init_data, x_session)
    q = (q or "").strip()[:64]
    digits = re.sub(r"\D", "", q)
    rows = await db.pool().fetch(
        """SELECT p.telegram_id, p.full_name, p.username, t.name AS team_name,
                  p.approved_at, p.disqualified_at,
                  COALESCE(sum(d.points) FILTER (WHERE d.status='accepted'),0)
                + COALESCE((SELECT sum(w.bonus_points) FROM weekly_summaries w
                             WHERE w.participant_id=p.telegram_id),0) AS points,
                  COALESCE(sum(d.steps) FILTER (WHERE d.status='accepted'),0) AS steps,
                  count(d.id) FILTER (WHERE d.status='accepted') AS days,
                  count(d.id) FILTER (WHERE d.status='pending')  AS pending,
                  max(d.entry_date) AS last_entry
             FROM participants p
             LEFT JOIN teams t ON t.id=p.team_id
             LEFT JOIN daily_entries d ON d.participant_id=p.telegram_id
            WHERE p.team_id IS NOT NULL
              AND ($1::text = '' OR p.full_name ILIKE $2::text OR p.username ILIKE $2::text
                   OR p.telegram_id::text = $1::text
                   OR (length($3::text) >= 4
                       AND regexp_replace(coalesce(p.phone,''), '[^0-9]', '', 'g')
                           LIKE '%' || $3::text || '%'))
            GROUP BY p.telegram_id, t.name
            ORDER BY (p.disqualified_at IS NOT NULL), (p.approved_at IS NULL), p.full_name
            LIMIT $4::int""",
        q, f"%{q.lstrip('@')}%", digits, ADMIN_LIST_LIMIT)
    def status(r) -> str:
        if r["disqualified_at"] is not None:
            return "dq"
        return "active" if r["approved_at"] is not None else "waiting"
    return {"items": [{"tg_id": r["telegram_id"], "name": r["full_name"] or "—",
                       "username": r["username"], "team": r["team_name"],
                       "status": status(r), "points": int(r["points"]),
                       "steps": int(r["steps"]), "days": int(r["days"]),
                       "pending": int(r["pending"]), "last": _iso(r["last_entry"])}
                      for r in rows]}


@app.get("/api/admin/participant/{tg_id}")
async def api_admin_participant(tg_id: int, x_init_data: str | None = Header(default=None),
                                x_session: str | None = Header(default=None)):
    """Карточка участника: профиль, итоги, календарь дней марафона, недельные отчёты."""
    await _require_admin(x_init_data, x_session)
    p = await db.user_detail(tg_id)
    if p is None or p["team_id"] is None:
        raise HTTPException(status_code=404, detail="not found")
    entries = {e["entry_date"]: e for e in await db.entries_for_admin(tg_id)}
    weekly = await db.weekly_rows(tg_id)
    today = datetime.now(config.tz).date()
    calendar, d = [], MARATHON_START
    while d <= MARATHON_END:
        e = entries.get(d)
        calendar.append({
            "date": d.isoformat(), "is_today": d == today, "future": d > today,
            "steps": e["steps"] if e else None, "points": e["points"] if e else 0,
            "status": e["status"] if e else None, "source": e["source"] if e else None,
            "shot": _shot_link(e["id"], e["screenshot_file_id"]) if e else None,
        })
        d = d.fromordinal(d.toordinal() + 1)
    weeks, monday = [], MARATHON_START - timedelta(days=MARATHON_START.weekday())
    while monday <= MARATHON_END:
        w = weekly.get(monday)
        weeks.append({"start": monday.isoformat(),
                      "reported": bool(w and w["reported_at"]),
                      "source": w["report_source"] if w else None,
                      "earned": int(w["earned_bonus"]) if w else 0,
                      "bonus": int(w["bonus_points"]) if w else 0})
        monday += timedelta(days=7)
    acc = [e for e in entries.values() if e["status"] == "accepted"]
    status = ("dq" if p["disqualified_at"] is not None
              else "active" if p["approved_at"] is not None else "waiting")
    return {
        "tg_id": tg_id, "name": p["full_name"] or "—", "username": p["username"],
        "phone": p["phone"], "team": p["team_name"], "status": status,
        "registered": _iso(p["created_at"]),
        "points": sum(e["points"] for e in acc) + sum(w["bonus"] for w in weeks),
        "steps": sum(e["steps"] for e in acc), "days": len(acc),
        "streak": await db.live_streak_len(tg_id, today),
        "best_streak": _best_streak({e["entry_date"]: e["steps"] for e in acc}),
        "calendar": calendar, "weeks": weeks, "marathon": _marathon(),
    }


_http = None                     # общая aiohttp-сессия (keep-alive к api.telegram.org)
_SHOT_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_SHOT_CACHE_MAX = 60             # ~60 скринов по 100–300 КБ — до ~15 МБ памяти


async def _session():
    global _http
    import aiohttp
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession()
    return _http


async def _serve_screenshot(file_id: str):
    """Скачивает файл у Telegram на сервере и отдаёт как изображение —
    токен бота наружу не попадает. Последние скрины держим в памяти:
    очередь проверки и карточки участников открывают одни и те же."""
    import aiohttp
    from fastapi.responses import Response

    if file_id.startswith("doc:"):          # скрин, присланный файлом
        file_id = file_id[4:]
    hit = _SHOT_CACHE.get(file_id)
    if hit:
        _SHOT_CACHE.move_to_end(file_id)
        return Response(content=hit[0], media_type=hit[1],
                        headers={"Cache-Control": "private, max-age=3600"})

    api = f"https://api.telegram.org/bot{config.bot_token}"
    s = await _session()
    async with s.get(f"{api}/getFile", params={"file_id": file_id},
                     timeout=aiohttp.ClientTimeout(total=20)) as r:
        meta = await r.json()
    if not meta.get("ok"):
        raise HTTPException(status_code=404, detail="file expired")
    path = meta["result"]["file_path"]
    async with s.get(f"https://api.telegram.org/file/bot{config.bot_token}/{path}",
                     timeout=aiohttp.ClientTimeout(total=30)) as r:
        if r.status != 200:                 # ошибку Telegram не кэшируем и не отдаём как картинку
            raise HTTPException(status_code=502, detail="file download failed")
        data = await r.read()
    ext = path.rsplit(".", 1)[-1].lower()
    media = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    _SHOT_CACHE[file_id] = (data, media)
    while len(_SHOT_CACHE) > _SHOT_CACHE_MAX:
        _SHOT_CACHE.popitem(last=False)
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


@app.post("/api/timing")
async def api_timing(request: Request):
    """Замеры открытия Mini App с телефона (мс от старта страницы). Медленные
    (> 2 с до показа) пишем в лог — так видно, где теряется время:
    init (ожидание данных Telegram), api_start→api_done (сеть + сервер)."""
    try:
        data = await request.json()
        m = {k: int(v) for k, v in (data.get("m") or {}).items()}
    except Exception:  # noqa: BLE001
        return {"ok": False}
    if m.get("shown", 0) > 2000:
        _log.warning("медленное открытие Mini App (%s %s): %s",
                     str(data.get("p"))[:20], str(data.get("v"))[:10], m)
    return {"ok": True}


@app.get("/health")
async def health():
    # Бот пингует /health каждые 10 минут — заодно держим пул БД «тёплым».
    # commit — какой коммит сейчас в проде (RENDER_GIT_COMMIT ставит Render):
    # по нему отслеживаем, докатился ли деплой.
    commit = os.getenv("RENDER_GIT_COMMIT", "")[:7] or None
    try:
        await db.pool().fetchval("SELECT 1")
    except Exception:  # noqa: BLE001
        return {"ok": True, "db": False, "commit": commit}
    return {"ok": True, "db": True, "commit": commit}


@app.get("/")
async def index():
    # no-cache: WKWebView в iOS Telegram иначе кэширует страницу эвристически
    # и после деплоя пользователи подолгу видят старую версию фронтенда.
    return FileResponse(_STATIC / "index.html",
                        headers={"Cache-Control": "no-cache"})


class _CachedStatic(StaticFiles):
    """Картинки (hero.jpg, prize-buds.png) раньше перезапрашивались при каждом
    открытии. Час — из кэша без запроса, ещё сутки — показ из кэша с фоновой
    проверкой. index.html отдаётся отдельно с no-cache."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
        return resp


app.mount("/", _CachedStatic(directory=_STATIC), name="static")
