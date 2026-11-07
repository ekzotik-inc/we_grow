"""Интеграционные тесты на настоящем PostgreSQL (TEST_DATABASE_URL).

Проверяют то, от чего зависят призы: серия, недельный бонус (только с
отчётом), командный зачёт (среднее, без дисквалифицированных, тай-брейк),
модерация (атомарность, пуши, DQ), итоги финала — и реальные SQL-запросы
админки Mini App (которые раньше проверялись только на подменённой БД).
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.conftest import FakeBot, needs_db, run

pytestmark = needs_db

MON = date(2026, 11, 2)           # понедельник, первый день марафона


async def team(name: str) -> int:
    from bot import db
    await db.create_team(name)
    return await db.pool().fetchval("SELECT id FROM teams WHERE name=$1", name)


async def person(tg: int, name: str, team_id: int, dq: bool = False) -> None:
    from bot import db
    now = datetime.now(timezone.utc)
    await db.pool().execute(
        """INSERT INTO participants (telegram_id, full_name, team_id, approved_at, disqualified_at)
           VALUES ($1,$2,$3,$4,$5)""", tg, name, team_id, now, now if dq else None)


async def entry(tg: int, day: date, steps: int, status: str = "accepted") -> int:
    from backend.scoring import points_for_steps
    from bot import db
    pts = points_for_steps(steps) if status == "accepted" else 0
    return await db.pool().fetchval(
        """INSERT INTO daily_entries (participant_id, entry_date, steps, points, status, source,
                                      screenshot_file_id)
           VALUES ($1,$2,$3,$4,$5,'manual','AgACfake') RETURNING id""",
        tg, day, steps, pts, status)


# ---- серия -----------------------------------------------------------------

def test_streak_counts_only_accepted_days_and_ignores_moderation_order():
    async def scenario():
        from bot import db
        t = await team("Альфа")
        await person(10, "Анна", t)
        ids = [await entry(10, MON + timedelta(days=i), 12000, "pending") for i in range(3)]
        bot = FakeBot()
        from bot import moderation
        for i in (2, 0, 1):                       # принимаем вразнобой
            assert (await moderation.accept(bot, ids[i])).ok
        row = await db.pool().fetchrow("SELECT * FROM streaks WHERE participant_id=10")
        assert row["current_len"] == 3 and row["last_qualifying_date"] == MON + timedelta(days=2)
        assert await db.live_streak_len(10, MON + timedelta(days=3)) == 3   # вчера — жива
        assert await db.live_streak_len(10, MON + timedelta(days=5)) == 0   # пропуск — сгорела
    run(scenario)


# ---- недельный бонус -------------------------------------------------------

def test_weekly_bonus_counts_only_with_report():
    async def scenario():
        from bot import db
        t = await team("Альфа")
        await person(10, "Анна", t)
        for i in range(7):
            await entry(10, MON + timedelta(days=i), 11000)
        ch = await db.recompute_weekly_bonus_change(10, MON)
        assert (ch.earned, ch.new, ch.reported) == (4, 0, False)     # заработан, но не засчитан
        assert await db.total_points(10) == 14                        # 7 × 2, без бонуса
        await db.save_weekly_report(10, MON, "AgACweek")
        ch = await db.recompute_weekly_bonus_change(10, MON)
        assert (ch.earned, ch.new, ch.reported) == (4, 4, True)
        assert await db.total_points(10) == 18
    run(scenario)


# ---- командный зачёт -------------------------------------------------------

def test_team_leaderboard_average_excludes_dq_and_breaks_ties_by_full_days():
    async def scenario():
        from bot import db
        a, b = await team("Альфа"), await team("Бета")
        await person(1, "А1", a)
        await person(2, "А2", a)
        await person(3, "Б1", b)
        await person(4, "Б2", b)
        await person(5, "Читер", b, dq=True)
        # Альфа: 4 и 2 балла → среднее 3; оба в один день 10K+ → full_days=1
        await entry(1, MON, 20000)                      # 4
        await entry(2, MON, 10000)                      # 2
        # Бета: 3 и 3 → среднее 3, но в разные дни → full_days=0
        await entry(3, MON, 15000)
        await entry(4, MON + timedelta(days=1), 15000)
        await entry(5, MON, 25000)                      # дисквалифицирован — не считается
        board = await db.team_leaderboard()
        assert [(t["name"], float(t["points"]), t["members"]) for t in board] == \
            [("Альфа", 3.0, 2), ("Бета", 3.0, 2)]
        assert board[0]["full_days"] == 1 and board[1]["full_days"] == 0
        by = await db.members_by_team()
        assert [m["full_name"] for m in by[a]] == ["А1", "А2"]           # по убыванию баллов
        assert "Читер" not in [m["full_name"] for m in by[b]]
    run(scenario)


# ---- модерация ---------------------------------------------------------------

def test_moderation_is_atomic_and_pushes_once():
    async def scenario():
        from bot import db, moderation
        t = await team("Альфа")
        await person(10, "Анна", t)
        eid = await entry(10, MON, 16000, "pending")
        bot = FakeBot()
        first = await moderation.accept(bot, eid)
        second = await moderation.accept(bot, eid)     # второй админ / двойное нажатие
        rej = await moderation.reject(bot, eid)
        assert first.ok and first.points == 3
        assert (second.code, rej.code) == ("done", "done")
        assert [c for c, _ in bot.sent].count(10) == 1           # участнику — один пуш
        row = await db.entry_by_id(eid)
        assert (row["status"], row["points"]) == ("accepted", 3)
    run(scenario)


def test_moderation_reject_and_disqualified():
    async def scenario():
        from bot import db, moderation
        t = await team("Альфа")
        await person(10, "Анна", t)
        await person(11, "Борис", t, dq=True)
        e1 = await entry(10, MON, 12000, "pending")
        e2 = await entry(11, MON, 12000, "pending")
        bot = FakeBot()
        assert (await moderation.reject(bot, e1)).code == "rejected"
        assert (await db.entry_by_id(e1))["status"] == "rejected"
        dq = await moderation.accept(bot, e2)
        assert dq.code == "disqualified"
        assert (await db.entry_by_id(e2))["status"] == "pending"   # вернётся при восстановлении
    run(scenario)


# ---- финал -------------------------------------------------------------------

def test_final_standings_and_personal_stats():
    async def scenario():
        from bot import final
        a, b = await team("Альфа"), await team("Бета")
        await person(1, "Анна", a)
        await person(2, "Борис", b)
        for i in range(3):
            await entry(1, MON + timedelta(days=i), 12000)
        await entry(1, MON + timedelta(days=4), 21000)
        await entry(2, MON, 6000)
        st = await final.standings()
        assert st.winner["name"] == "Альфа" and st.pending == 0
        people = {p.tg_id: p for p in await final.personals(st)}
        anna = people[1]
        assert (anna.steps, anna.days, anna.best_day, anna.best_streak) == (57000, 4, 21000, 3)
        assert anna.points == 10 and anna.champion and anna.team_rank == 1
        assert not people[2].champion and people[2].team_rank == 2
        assert await final.claim_send("Альфа") is True
        assert await final.claim_send("Альфа") is False             # повторно — нельзя
    run(scenario)


# ---- SQL админки Mini App на настоящей базе ------------------------------------

def test_admin_api_endpoints_on_real_db():
    """Реальные запросы /api/admin/* (раньше — только на фейковой БД)."""
    async def seed():
        t = await team("Альфа")
        await person(10, "Анна Ким", t)
        await entry(10, MON, 12000)
        await entry(10, MON + timedelta(days=1), 31000, "pending")
        from bot import db
        await db.pool().execute(
            "INSERT INTO participants (telegram_id, full_name, username) VALUES (20,'Новичок','nov')")
    run(seed)

    from fastapi.testclient import TestClient
    from webapp import server
    with TestClient(server.app) as c:
        h = {"X-Session": server._make_token(1)}          # ADMIN_IDS=1
        r = c.get("/api/admin/overview", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["queue"] == 1
        q = c.get("/api/admin/queue", headers=h).json()
        assert [e["steps"] for e in q["entries"]] == [31000] and q["entries"][0]["big"]
        assert isinstance(q["registrations"], list)
        for query in ("", "Анна", "@nov", "10", "ким"):
            r = c.get("/api/admin/participants", params={"q": query}, headers=h)
            assert r.status_code == 200, (query, r.text)
        assert any(p["name"] == "Анна Ким" for p in
                   c.get("/api/admin/participants", params={"q": "ким"}, headers=h).json()["items"])
        card = c.get("/api/admin/participant/10", headers=h)
        assert card.status_code == 200, card.text
        assert c.get("/api/admin/overview", headers={"X-Session": server._make_token(10)}).status_code == 403
        # модерация из Mini App
        eid = q["entries"][0]["id"]
        m = c.post("/api/admin/moderate", json={"entry_id": eid, "action": "accept"}, headers=h).json()
        assert m["ok"] and m["code"] == "accepted" and m["points"] == 4 and m["left"] == 0
        again = c.post("/api/admin/moderate", json={"entry_id": eid, "action": "reject"}, headers=h)
        assert again.json()["code"] == "done"
        assert c.post("/api/admin/moderate", json={"entry_id": eid, "action": "drop"},
                      headers=h).status_code == 400
        # публичные эндпоинты с тем же набором данных
        assert c.get("/api/leaderboard", headers=h).json()["final"]["announced"] is False
        assert c.get("/api/team", headers=h).status_code == 200
        assert c.get("/api/me", headers={"X-Session": server._make_token(10)}).json()["registered"]
