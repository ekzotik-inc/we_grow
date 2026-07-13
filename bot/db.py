"""Слой доступа к PostgreSQL на asyncpg.

Один пул на процесс. Функции возвращают простые dict/значения, чтобы хендлеры
не зависели от драйвера.
"""
from __future__ import annotations

import ssl as ssl_module
from datetime import date, datetime, timedelta, timezone
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
    # search_path=wegrow — все запросы работают внутри нашей схемы, изолированно
    # от прочих объектов базы. Схему создаёт schema.sql ниже.
    _pool = await asyncpg.create_pool(
        dsn, min_size=1, max_size=10, ssl=_ssl_for(dsn),
        server_settings={"search_path": "wegrow"},
    )
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


async def reset_participant(tg_id: int) -> None:
    """Полностью удаляет участника и все его данные — /start начнётся заново."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM daily_entries WHERE participant_id=$1", tg_id)
            await conn.execute("DELETE FROM weekly_summaries WHERE participant_id=$1", tg_id)
            await conn.execute("DELETE FROM streaks WHERE participant_id=$1", tg_id)
            await conn.execute("DELETE FROM participants WHERE telegram_id=$1", tg_id)


async def set_consent(tg_id: int) -> None:
    await pool().execute(
        "UPDATE participants SET consent_at=$2 WHERE telegram_id=$1",
        tg_id, datetime.now(timezone.utc),
    )


async def set_profile(tg_id: int, full_name: str, is_asr: bool, username: str | None = None) -> None:
    await pool().execute(
        "UPDATE participants SET full_name=$2, is_asr=$3, username=$4 WHERE telegram_id=$1",
        tg_id, full_name, is_asr, username,
    )


async def set_team(tg_id: int, team_id: int) -> None:
    await pool().execute(
        "UPDATE participants SET team_id=$2 WHERE telegram_id=$1", tg_id, team_id
    )


async def set_role(tg_id: int, role: str) -> None:
    await pool().execute(
        "UPDATE participants SET role=$2 WHERE telegram_id=$1", tg_id, role
    )


async def participants_page(offset: int, limit: int = 8) -> list[asyncpg.Record]:
    return await pool().fetch(
        """SELECT p.telegram_id, p.full_name, p.username, p.approved_at,
                  p.disqualified_at, p.created_at, t.name AS team_name
             FROM participants p LEFT JOIN teams t ON t.id=p.team_id
            WHERE p.team_id IS NOT NULL
            ORDER BY (p.approved_at IS NOT NULL), p.created_at DESC
            OFFSET $1 LIMIT $2""", offset, limit)


async def participants_count() -> int:
    return int(await pool().fetchval(
        "SELECT count(*) FROM participants WHERE team_id IS NOT NULL"))


async def pending_participants() -> list[asyncpg.Record]:
    return await pool().fetch(
        """SELECT p.telegram_id, p.full_name, p.username, p.created_at, t.name AS team_name
             FROM participants p LEFT JOIN teams t ON t.id=p.team_id
            WHERE p.team_id IS NOT NULL AND p.approved_at IS NULL
              AND p.disqualified_at IS NULL
            ORDER BY p.created_at""")


async def status_counts() -> dict[str, int]:
    row = await pool().fetchrow(
        """SELECT
             count(*) FILTER (WHERE team_id IS NOT NULL) AS total,
             count(*) FILTER (WHERE approved_at IS NOT NULL AND disqualified_at IS NULL) AS approved,
             count(*) FILTER (WHERE team_id IS NOT NULL AND approved_at IS NULL
                                AND disqualified_at IS NULL) AS pending,
             count(*) FILTER (WHERE disqualified_at IS NOT NULL) AS disq
           FROM participants""")
    return dict(row)


async def undisqualify(tg_id: int) -> None:
    await pool().execute("UPDATE participants SET disqualified_at=NULL WHERE telegram_id=$1", tg_id)


async def user_detail(tg_id: int) -> asyncpg.Record | None:
    return await pool().fetchrow(
        """SELECT p.*, t.name AS team_name
             FROM participants p LEFT JOIN teams t ON t.id=p.team_id
            WHERE p.telegram_id=$1""", tg_id)


async def all_settings() -> dict[str, str]:
    rows = await pool().fetch("SELECT key, value FROM settings")
    return {r["key"]: r["value"] for r in rows}


async def set_setting(key: str, value: str | None) -> None:
    if value is None:
        await pool().execute("DELETE FROM settings WHERE key=$1", key)
    else:
        await pool().execute(
            "INSERT INTO settings (key, value) VALUES ($1,$2) "
            "ON CONFLICT (key) DO UPDATE SET value=$2", key, value,
        )


async def move_to_team(tg_id: int, team_id: int) -> None:
    await pool().execute("UPDATE participants SET team_id=$2 WHERE telegram_id=$1", tg_id, team_id)


async def find_participants(query: str, limit: int = 10) -> list[asyncpg.Record]:
    """Поиск участника по ID или части ФИО/username для перевода в команду."""
    if query.isdigit():
        rows = await pool().fetch(
            """SELECT p.telegram_id, p.full_name, t.name AS team_name
                 FROM participants p LEFT JOIN teams t ON t.id=p.team_id
                WHERE p.telegram_id=$1""", int(query))
        if rows:
            return rows
    pat = f"%{query}%"
    return await pool().fetch(
        """SELECT p.telegram_id, p.full_name, t.name AS team_name
             FROM participants p LEFT JOIN teams t ON t.id=p.team_id
            WHERE p.full_name ILIKE $1 OR p.username ILIKE $1
            ORDER BY p.full_name LIMIT $2""", pat, limit)


async def set_approved(tg_id: int) -> None:
    await pool().execute(
        "UPDATE participants SET approved_at=$2 WHERE telegram_id=$1",
        tg_id, datetime.now(timezone.utc),
    )


async def all_active_ids() -> list[int]:
    """ID подтверждённых, не дисквалифицированных участников (для рассылок)."""
    rows = await pool().fetch(
        "SELECT telegram_id FROM participants "
        "WHERE approved_at IS NOT NULL AND disqualified_at IS NULL"
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
        return StreakState(0, None)
    return StreakState(row["current_len"], row["last_qualifying_date"])


async def save_submission(tg_id: int, day: date, steps: int, screenshot_file_id: str) -> int:
    """Участник отправил результат на модерацию: статус pending, points=0.
    Повторная отправка того же дня перезаписывает (например, после отклонения)."""
    return int(await pool().fetchval(
        """INSERT INTO daily_entries
             (participant_id, entry_date, steps, points, status, source, screenshot_file_id)
           VALUES ($1,$2,$3,0,'pending','manual',$4)
           ON CONFLICT (participant_id, entry_date) DO UPDATE
             SET steps=$3, points=0, status='pending',
                 screenshot_file_id=$4, reviewed_at=NULL, created_at=now()
           RETURNING id""",
        tg_id, day, steps, screenshot_file_id))


async def entry_by_id(entry_id: int) -> asyncpg.Record | None:
    return await pool().fetchrow(
        """SELECT d.*, p.full_name, p.username, t.name AS team_name
             FROM daily_entries d
             JOIN participants p ON p.telegram_id=d.participant_id
             LEFT JOIN teams t ON t.id=p.team_id
            WHERE d.id=$1""", entry_id)


async def pending_submissions(limit: int = 20) -> list[asyncpg.Record]:
    return await pool().fetch(
        """SELECT d.id, d.participant_id, d.entry_date, d.steps, d.screenshot_file_id,
                  p.full_name, p.username, t.name AS team_name
             FROM daily_entries d
             JOIN participants p ON p.telegram_id=d.participant_id
             LEFT JOIN teams t ON t.id=p.team_id
            WHERE d.status='pending'
            ORDER BY d.created_at LIMIT $1""", limit)


async def pending_submissions_count() -> int:
    return int(await pool().fetchval("SELECT count(*) FROM daily_entries WHERE status='pending'"))


async def set_entry_status(entry_id: int, status: str, points: int) -> None:
    await pool().execute(
        "UPDATE daily_entries SET status=$2, points=$3, reviewed_at=now() WHERE id=$1",
        entry_id, status, points)


async def recompute_streak(tg_id: int) -> StreakState:
    """Пересчитывает серию по принятым дням (устойчиво к порядку модерации)."""
    from backend.scoring import StreakState, update_streak
    rows = await pool().fetch(
        "SELECT entry_date, steps FROM daily_entries "
        "WHERE participant_id=$1 AND status='accepted' ORDER BY entry_date", tg_id)
    state = StreakState(0, None)
    for r in rows:
        state = update_streak(state, r["entry_date"], r["steps"]).state
    await pool().execute(
        """INSERT INTO streaks (participant_id, current_len, last_qualifying_date)
           VALUES ($1,$2,$3)
           ON CONFLICT (participant_id) DO UPDATE
             SET current_len=$2, last_qualifying_date=$3""",
        tg_id, state.current_len, state.last_qualifying_date)
    return state


async def week_steps(tg_id: int, monday: date) -> list[int]:
    """Принятые шаги участника за 7 дней недели (пн..вс), 0 для несданных."""
    rows = await pool().fetch(
        """SELECT entry_date, steps FROM daily_entries
            WHERE participant_id=$1 AND status='accepted'
              AND entry_date >= $2 AND entry_date < $2 + 7""",
        tg_id, monday,
    )
    by_date = {r["entry_date"]: r["steps"] for r in rows}
    return [by_date.get(monday + timedelta(days=i), 0) for i in range(7)]


async def award_weekly_bonus(tg_id: int, monday: date, bonus: int, week_total: int) -> None:
    """Начисляет/обновляет недельный бонус за серию (идемпотентно по неделе)."""
    await pool().execute(
        """INSERT INTO weekly_summaries
             (participant_id, week_start, reported_total, computed_total, reconciled, bonus_points)
           VALUES ($1,$2,$3,$3,false,$4)
           ON CONFLICT (participant_id, week_start) DO UPDATE
             SET computed_total=$3, bonus_points=$4""",
        tg_id, monday, week_total, bonus,
    )


async def total_points(tg_id: int) -> int:
    """Сумма баллов участника: дневные + недельные бонусы за серию."""
    val = await pool().fetchval(
        """SELECT COALESCE((SELECT sum(points) FROM daily_entries
                             WHERE participant_id=$1 AND status='accepted'),0)
                + COALESCE((SELECT sum(bonus_points) FROM weekly_summaries WHERE participant_id=$1),0)""",
        tg_id,
    )
    return int(val)


async def ids_without_entry_today(day: date) -> list[int]:
    rows = await pool().fetch(
        """SELECT p.telegram_id FROM participants p
            WHERE p.approved_at IS NOT NULL AND p.disqualified_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM daily_entries d
                   WHERE d.participant_id = p.telegram_id AND d.entry_date = $1)""",
        day,
    )
    return [r["telegram_id"] for r in rows]


# ---- Лидерборд -----------------------------------------------------------

async def team_leaderboard() -> list[asyncpg.Record]:
    # Дневные баллы и недельные бонусы считаем отдельными подзапросами,
    # чтобы join'ы не размножали строки.
    return await pool().fetch(
        """SELECT t.name,
                  COALESCE((SELECT sum(d.points) FROM daily_entries d
                              JOIN participants p ON p.telegram_id=d.participant_id
                             WHERE p.team_id=t.id AND p.approved_at IS NOT NULL
                               AND p.disqualified_at IS NULL AND d.status='accepted'),0)
                + COALESCE((SELECT sum(w.bonus_points) FROM weekly_summaries w
                              JOIN participants p ON p.telegram_id=w.participant_id
                             WHERE p.team_id=t.id AND p.disqualified_at IS NULL),0) AS points
             FROM teams t ORDER BY points DESC, t.name"""
    )


async def top_participants(limit: int = 10) -> list[asyncpg.Record]:
    return await pool().fetch(
        """SELECT p.full_name,
                  COALESCE((SELECT sum(d.points) FROM daily_entries d
                             WHERE d.participant_id=p.telegram_id AND d.status='accepted'),0)
                + COALESCE((SELECT sum(w.bonus_points) FROM weekly_summaries w
                             WHERE w.participant_id=p.telegram_id),0) AS points
             FROM participants p
            WHERE p.disqualified_at IS NULL AND p.approved_at IS NOT NULL
            ORDER BY points DESC, p.full_name LIMIT $1""",
        limit,
    )


# ---- Данные для админ-панели ---------------------------------------------

async def pending_reviews(limit: int = 10) -> list[asyncpg.Record]:
    """Записи, помеченные на проверку P&C (>30k, расхождения)."""
    return await pool().fetch(
        """SELECT d.entry_date, d.steps, p.full_name, d.participant_id
             FROM daily_entries d JOIN participants p ON p.telegram_id=d.participant_id
            WHERE d.needs_review ORDER BY d.entry_date DESC, d.id DESC LIMIT $1""",
        limit,
    )


async def engagement(day: date) -> tuple[int, int]:
    """(сдали сегодня, всего активных) для сводки вовлечённости."""
    active = await pool().fetchval(
        "SELECT count(*) FROM participants WHERE approved_at IS NOT NULL AND disqualified_at IS NULL"
    )
    submitted = await pool().fetchval(
        """SELECT count(DISTINCT d.participant_id) FROM daily_entries d
             JOIN participants p ON p.telegram_id=d.participant_id
            WHERE d.entry_date=$1 AND p.approved_at IS NOT NULL AND p.disqualified_at IS NULL""",
        day,
    )
    return int(submitted), int(active)


# ---- Данные для Mini App -------------------------------------------------

async def participant_card(tg_id: int) -> asyncpg.Record | None:
    """Профиль участника с названием команды."""
    return await pool().fetchrow(
        """SELECT p.telegram_id, p.full_name, p.team_id, p.disqualified_at,
                  t.name AS team_name
             FROM participants p LEFT JOIN teams t ON t.id = p.team_id
            WHERE p.telegram_id = $1""",
        tg_id,
    )


async def entries_list(tg_id: int) -> list[asyncpg.Record]:
    """Все дневные записи участника (для календаря марафона)."""
    return await pool().fetch(
        "SELECT entry_date, steps, points FROM daily_entries "
        "WHERE participant_id=$1 ORDER BY entry_date",
        tg_id,
    )


async def team_members(team_id: int) -> list[asyncpg.Record]:
    """Состав команды с вкладом каждого (дневные баллы + недельные бонусы)."""
    return await pool().fetch(
        """SELECT p.full_name,
                  COALESCE((SELECT sum(d.points) FROM daily_entries d
                             WHERE d.participant_id=p.telegram_id AND d.status='accepted'),0)
                + COALESCE((SELECT sum(w.bonus_points) FROM weekly_summaries w
                             WHERE w.participant_id=p.telegram_id),0) AS points
             FROM participants p
            WHERE p.team_id=$1 AND p.approved_at IS NOT NULL AND p.disqualified_at IS NULL
            ORDER BY points DESC, p.full_name""",
        team_id,
    )
