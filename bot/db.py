"""Слой доступа к PostgreSQL на asyncpg.

Один пул на процесс. Функции возвращают простые dict/значения, чтобы хендлеры
не зависели от драйвера.
"""
from __future__ import annotations

import ssl as ssl_module
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg

from backend.scoring import StreakState

_pool: asyncpg.Pool | None = None
_SCHEMA = Path(__file__).resolve().parent.parent / "backend" / "db" / "schema.sql"


def _ssl_for(dsn: str):
    """Render (и большинство облачных Postgres) требуют TLS для внешних
    подключений. Определяем по sslmode в строке или по хосту render.com.
    Для локального Postgres SSL не нужен."""
    if "sslmode=disable" in dsn:
        return None
    if "sslmode=require" in dsn or "render.com" in dsn:
        ctx = ssl_module.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_NONE
        return ctx
    return None


async def connect(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10, ssl=_ssl_for(dsn))
    # Идемпотентная схема — применяем на старте, чтобы бот поднимался «из коробки».
    async with _pool.acquire() as conn:
        await conn.execute(_SCHEMA.read_text(encoding="utf-8"))


async def close() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "db.connect() не вызван"
    return _pool


# ---- Участники -----------------------------------------------------------

async def get_participant(tg_id: int) -> asyncpg.Record | None:
    return await pool().fetchrow("SELECT * FROM participants WHERE telegram_id=$1", tg_id)


async def upsert_participant_start(tg_id: int) -> None:
    """Гарантирует запись участника при /start (без анкеты)."""
    await pool().execute(
        """INSERT INTO participants (telegram_id, full_name)
           VALUES ($1, '') ON CONFLICT (telegram_id) DO NOTHING""",
        tg_id,
    )


async def set_consent(tg_id: int) -> None:
    await pool().execute(
        "UPDATE participants SET consent_at=$2 WHERE telegram_id=$1",
        tg_id, datetime.now(timezone.utc),
    )


async def set_profile(tg_id: int, full_name: str, is_asr: bool) -> None:
    await pool().execute(
        "UPDATE participants SET full_name=$2, is_asr=$3 WHERE telegram_id=$1",
        tg_id, full_name, is_asr,
    )


async def set_team(tg_id: int, team_id: int) -> None:
    await pool().execute(
        "UPDATE participants SET team_id=$2 WHERE telegram_id=$1", tg_id, team_id
    )


async def set_role(tg_id: int, role: str) -> None:
    await pool().execute(
        "UPDATE participants SET role=$2 WHERE telegram_id=$1", tg_id, role
    )


async def all_active_ids() -> list[int]:
    rows = await pool().fetch(
        "SELECT telegram_id FROM participants WHERE consent_at IS NOT NULL"
    )
    return [r["telegram_id"] for r in rows]


# ---- Команды -------------------------------------------------------------

async def teams_with_capacity() -> list[asyncpg.Record]:
    """Команды со счётчиком занятых мест."""
    return await pool().fetch(
        """SELECT t.id, t.name, t.capacity,
                  count(p.telegram_id) FILTER (WHERE p.team_id = t.id) AS taken
             FROM teams t
             LEFT JOIN participants p ON p.team_id = t.id
            GROUP BY t.id ORDER BY t.id"""
    )


async def open_teams() -> list[asyncpg.Record]:
    return [t for t in await teams_with_capacity() if t["taken"] < t["capacity"]]


# ---- Дни и серии ---------------------------------------------------------

async def get_entry(tg_id: int, day: date) -> asyncpg.Record | None:
    return await pool().fetchrow(
        "SELECT * FROM daily_entries WHERE participant_id=$1 AND entry_date=$2", tg_id, day
    )


async def get_streak(tg_id: int) -> StreakState:
    row = await pool().fetchrow("SELECT * FROM streaks WHERE participant_id=$1", tg_id)
    if row is None:
        return StreakState(0, None, 0)
    return StreakState(row["current_len"], row["last_qualifying_date"], row["bonus_awarded_cycles"])


async def save_entry_and_streak(
    tg_id: int, day: date, steps: int, points: int, source: str,
    screenshot_file_id: str | None, needs_review: bool, new_streak: StreakState,
) -> None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO daily_entries
                     (participant_id, entry_date, steps, points, source, screenshot_file_id, needs_review)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT (participant_id, entry_date) DO UPDATE
                     SET steps=$3, points=$4, source=$5,
                         screenshot_file_id=COALESCE($6, daily_entries.screenshot_file_id),
                         needs_review=$7""",
                tg_id, day, steps, points, source, screenshot_file_id, needs_review,
            )
            await conn.execute(
                """INSERT INTO streaks (participant_id, current_len, last_qualifying_date, bonus_awarded_cycles)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (participant_id) DO UPDATE
                     SET current_len=$2, last_qualifying_date=$3, bonus_awarded_cycles=$4""",
                tg_id, new_streak.current_len, new_streak.last_qualifying_date,
                new_streak.bonus_awarded_cycles,
            )


async def total_points(tg_id: int) -> int:
    val = await pool().fetchval(
        "SELECT COALESCE(sum(points),0) FROM daily_entries WHERE participant_id=$1", tg_id
    )
    return int(val)


async def ids_without_entry_today(day: date) -> list[int]:
    rows = await pool().fetch(
        """SELECT p.telegram_id FROM participants p
            WHERE p.consent_at IS NOT NULL AND p.disqualified_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM daily_entries d
                   WHERE d.participant_id = p.telegram_id AND d.entry_date = $1)""",
        day,
    )
    return [r["telegram_id"] for r in rows]


# ---- Лидерборд -----------------------------------------------------------

async def team_leaderboard() -> list[asyncpg.Record]:
    return await pool().fetch(
        """SELECT t.name,
                  COALESCE(sum(d.points),0) AS points
             FROM teams t
             LEFT JOIN participants p ON p.team_id = t.id AND p.disqualified_at IS NULL
             LEFT JOIN daily_entries d ON d.participant_id = p.telegram_id
            GROUP BY t.id ORDER BY points DESC, t.name"""
    )


async def top_participants(limit: int = 10) -> list[asyncpg.Record]:
    return await pool().fetch(
        """SELECT p.full_name, COALESCE(sum(d.points),0) AS points
             FROM participants p
             LEFT JOIN daily_entries d ON d.participant_id = p.telegram_id
            WHERE p.disqualified_at IS NULL AND p.consent_at IS NOT NULL
            GROUP BY p.telegram_id ORDER BY points DESC, p.full_name LIMIT $1""",
        limit,
    )
