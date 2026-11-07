"""Общая настройка тестов.

Чистые тесты (серии, алерты, картинка итогов) работают без БД.
Интеграционные (test_db_*.py) идут на настоящем PostgreSQL из
TEST_DATABASE_URL — в GitHub Actions его поднимает сервис postgres
(.github/workflows/tests.yml); без переменной они пропускаются.
ВНИМАНИЕ: интеграционные тесты очищают таблицы схемы wegrow — никогда не
указывайте в TEST_DATABASE_URL боевую базу.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = os.getenv("TEST_DATABASE_URL", "")
# В CI интеграционные тесты обязаны идти на базе, а не тихо пропускаться.
if os.getenv("GITHUB_ACTIONS") and not TEST_DB:
    raise RuntimeError("TEST_DATABASE_URL не задан в CI — интеграционные тесты не запустятся")
# config читает env при импорте — задаём ДО любых импортов bot.*
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "1"
os.environ["PREMIUM_EMOJI"] = "false"
os.environ["DATABASE_URL"] = TEST_DB or "postgresql://test:test@localhost:5432/test"

needs_db = pytest.mark.skipif(not TEST_DB, reason="нужен TEST_DATABASE_URL (PostgreSQL)")


class FakeBot:
    """Вместо Telegram: запоминает исходящие сообщения."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.edited: list[dict] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def edit_message_caption(self, **kw):
        self.edited.append(kw)


async def fresh_db():
    """Подключение к тестовой БД (схема применяется) + пустые таблицы."""
    from bot import db
    if db._pool is not None:
        await db.close()
        db._pool = None
    await db.connect(TEST_DB)
    tables = await db.pool().fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='wegrow'")
    names = ", ".join(f"wegrow.{r['tablename']}" for r in tables)
    await db.pool().execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
    from bot import settings
    await settings.load()
    return db


def run(coro_fn):
    """Запустить асинхронный сценарий на свежей БД и закрыть пул."""
    async def wrapper():
        from bot import db
        await fresh_db()
        try:
            return await coro_fn()
        finally:
            await db.close()
            db._pool = None
    return asyncio.run(wrapper())
