# Схема базы данных (PostgreSQL)

Черновая схема MVP. DDL — в [backend/db/schema.sql](../backend/db/schema.sql).

## Таблицы

### `participants`
Участник марафона.

| Поле | Тип | Описание |
|------|-----|----------|
| `telegram_id` | bigint PK | ID пользователя Telegram |
| `full_name` | text | ФИО из анкеты |
| `is_asr` | bool | признак «участник из нашего дружного коллектива» |
| `team_id` | int FK → teams | команда |
| `role` | text | `participant` \| `admin` (P&C) |
| `consent_at` | timestamptz | дата согласия с правилами (закрывает п. 6) |
| `disqualified_at` | timestamptz null | если дисквалифицирован |
| `created_at` | timestamptz | регистрация |

### `teams`
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int PK | |
| `name` | text | «Бамбук», «Секвойи», «Баобабы», «Эвкалипты» |
| `capacity` | int | максимум участников (напр. 10) |

Заполненность («Бамбук — 7/10») считается запросом `count(participants)` по
`team_id`; при онбординге показываем только команды с местами (закрывает п. 5).

### `daily_entries`
Один день одного участника.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | bigint PK | |
| `participant_id` | bigint FK | |
| `entry_date` | date | дата дня (по TZ марафона) |
| `steps` | int | подтверждённое число шагов |
| `points` | int | начислено по шкале |
| `source` | text | `ocr` \| `manual` |
| `screenshot_file_id` | text | Telegram file_id как доказательство |
| `needs_review` | bool | авто-флаг (≥30k, расхождение дат/сводки) |
| `created_at` | timestamptz | |

Уникальность: `(participant_id, entry_date)` — один зачёт в день.

### `streaks`
Денормализованное текущее состояние серии (для мгновенной обратной связи).

| Поле | Тип | Описание |
|------|-----|----------|
| `participant_id` | bigint PK FK | |
| `current_len` | int | дней подряд по 10 000+ |
| `last_qualifying_date` | date | последний день, продливший серию |
| `bonus_awarded_cycles` | int | сколько раз начислен бонус за 7 дней |

### `weekly_summaries`
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | bigint PK | |
| `participant_id` | bigint FK | |
| `week_start` | date | понедельник недели |
| `reported_total` | int | сумма из сводки приложения |
| `computed_total` | int | сумма ежедневных записей бота |
| `reconciled` | bool | сошлось ли в пределах допуска |
| `screenshot_file_id` | text | |

### `broadcasts`
Аудит ручных рассылок P&C.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | bigint PK | |
| `admin_id` | bigint FK | кто отправил |
| `text` | text | |
| `image_file_id` | text null | |
| `audience` | text | `all` \| `team:<id>` |
| `sent_at` | timestamptz | |
| `recipients` | int | доставлено |

## Индексы

- `daily_entries (participant_id, entry_date)` unique
- `daily_entries (needs_review) where needs_review` — лента модерации
- `participants (team_id)` — заполненность и командный зачёт
