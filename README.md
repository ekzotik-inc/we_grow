# Step Together 🪴

Командный шаговый марафон в Telegram (@wegrowmarathon_bot). Концепция
«Мы растём, когда двигаемся»: каждый участник «выращивает» растение,
шаги — энергия роста, команда — общий сад.

- **Марафон: 17 июля — 7 августа 2026** (таймзона Asia/Tashkent)
- Ведущий всех диалогов — маскот, росток **Stepy 🪴**

> 🤖 **Для Claude / новых сессий:** актуальный контекст проекта — в
> [CLAUDE.md](CLAUDE.md). Начинай с него.

## Из чего состоит система

| Часть | Стек | Роль |
|-------|------|------|
| Бот | Python 3.11+, aiogram 3.29 (polling) | онбординг, приём шагов + скринов, модерация P&C, админка, рассылки |
| БД | PostgreSQL (asyncpg), схема `wegrow` | участники, команды, результаты, серии, недельные бонусы |
| Mini App | FastAPI + vanilla JS (`webapp/`) | «Прогресс» (растение+календарь), «Команда», «Лидерборд», «Правила», «Призы», «Помощь» |
| Планировщик | APScheduler внутри бота | напоминания, недельные сводки, keep-alive webapp |
| Выгрузка | openpyxl | Excel для P&C: участники + результаты со ссылками на скрины |

Хостинг — **Render** (ветка `main`): worker `wegrow-bot`, web `wegrow-webapp`,
база `test_bd`. Конфигурация — [render.yaml](render.yaml).

## Как это работает

1. Участник регистрируется в боте: согласие → телефон → ФИО → команда.
2. P&C подтверждает заявку — участник допущен к марафону.
3. Каждый день до 23:55 участник шлёт число шагов + скриншот из Google Health (бывший Fitbit).
4. P&C принимает/отклоняет результат — только после принятия начисляются
   баллы (5000+ → 1, 10000+ → 2, 15000+ → 3) и растёт серия.
5. Бонус за серию по итогам недели: 5 дней 10000+ → +2, 7 дней → +4.

## Быстрый запуск локально

Нужны Docker (для PostgreSQL) и Python 3.11+.

```bash
docker compose up -d db          # 1. PostgreSQL (схема применится на старте бота)
cp .env.example .env             # 2. BOT_TOKEN и ADMIN_IDS
pip install -r requirements.txt  # 3. зависимости
python -m bot.main               # 4. бот
uvicorn webapp.server:app --port 8000   # 5. mini app (опционально)
```

Тесты логики баллов: `python -m pytest backend/test_scoring.py -q`.

## Документация

- [CLAUDE.md](CLAUDE.md) — **актуальное состояние проекта** и соглашения
- [docs/architecture.md](docs/architecture.md) — компоненты и потоки данных
- [docs/database.md](docs/database.md) — схема БД
- [docs/scoring.md](docs/scoring.md) — баллы, серии, граничные случаи
- [docs/user-flow.md](docs/user-flow.md) — онбординг и ежедневный цикл
- [docs/notifications.md](docs/notifications.md) — рассылки и напоминания
- [docs/admin.md](docs/admin.md) — админ-режим P&C
- [docs/deploy-render.md](docs/deploy-render.md) — деплой на Render
- [docs/premium-emoji.md](docs/premium-emoji.md) — премиум-эмодзи Telegram
- [docs/miniapp.md](docs/miniapp.md) — Mini App

## Структура репозитория

```
bot/        бот: хендлеры, тексты, клавиатуры, планировщик, Excel-выгрузка
backend/    логика баллов/серий (scoring.py) и схема БД (backend/db)
webapp/     Mini App: FastAPI-сервер + статичный фронт (рабочая версия)
miniapp/    устаревшая React-заготовка (в проде не используется)
scheduler/  устаревшая заготовка (планировщик живёт в bot/scheduler.py)
docs/       спецификации
```
