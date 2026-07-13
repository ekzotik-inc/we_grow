-- Step Together — схема БД (PostgreSQL). MVP.
-- Идемпотентна: можно применять повторно.
-- Времена дней считаются в TZ марафона (см. bot/config.py).
--
-- Все объекты живут в отдельной схеме wegrow, чтобы безопасно сосуществовать
-- с другими проектами в той же базе (напр. общая free-база Render).
CREATE SCHEMA IF NOT EXISTS wegrow;
SET search_path TO wegrow;

CREATE TABLE IF NOT EXISTS teams (
    id       serial PRIMARY KEY,
    name     text NOT NULL UNIQUE,
    capacity int  NOT NULL DEFAULT 10
);

CREATE TABLE IF NOT EXISTS participants (
    telegram_id     bigint PRIMARY KEY,
    full_name       text        NOT NULL,
    username        text,                                        -- @username на момент регистрации
    is_asr          boolean     NOT NULL DEFAULT false,
    team_id         int         REFERENCES teams(id),
    role            text        NOT NULL DEFAULT 'participant',  -- participant | admin
    consent_at      timestamptz,                                 -- согласие с правилами (п.6)
    approved_at     timestamptz,                                 -- подтверждение P&C (null = ожидает)
    disqualified_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS participants_team_idx ON participants(team_id);

-- Миграции для баз, созданных ранее.
ALTER TABLE participants ADD COLUMN IF NOT EXISTS username text;
ALTER TABLE participants ADD COLUMN IF NOT EXISTS approved_at timestamptz;

CREATE TABLE IF NOT EXISTS daily_entries (
    id                 bigserial PRIMARY KEY,
    participant_id     bigint  NOT NULL REFERENCES participants(telegram_id),
    entry_date         date    NOT NULL,
    steps              int     NOT NULL,
    points             int     NOT NULL,
    source             text    NOT NULL,          -- ocr | manual
    screenshot_file_id text,
    needs_review       boolean NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (participant_id, entry_date)
);

CREATE INDEX IF NOT EXISTS daily_review_idx ON daily_entries(needs_review) WHERE needs_review;

CREATE TABLE IF NOT EXISTS streaks (
    participant_id        bigint PRIMARY KEY REFERENCES participants(telegram_id),
    current_len           int  NOT NULL DEFAULT 0,   -- дней подряд по 10 000+ (для мотивации)
    last_qualifying_date  date
);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    id                 bigserial PRIMARY KEY,
    participant_id     bigint  NOT NULL REFERENCES participants(telegram_id),
    week_start         date    NOT NULL,
    reported_total     int     NOT NULL,
    computed_total     int     NOT NULL,
    reconciled         boolean NOT NULL DEFAULT false,
    bonus_points       int     NOT NULL DEFAULT 0,   -- недельный бонус за серию (правило 10)
    screenshot_file_id text,
    UNIQUE (participant_id, week_start)
);

-- Миграция для баз, созданных до появления bonus_points (напр. на Render).
ALTER TABLE weekly_summaries ADD COLUMN IF NOT EXISTS bonus_points int NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS broadcasts (
    id            bigserial PRIMARY KEY,
    admin_id      bigint  NOT NULL REFERENCES participants(telegram_id),
    text          text    NOT NULL,
    image_file_id text,
    audience      text    NOT NULL,   -- all | team:<id>
    sent_at       timestamptz NOT NULL DEFAULT now(),
    recipients    int     NOT NULL DEFAULT 0
);

-- Стартовые команды (тема «растения»).
INSERT INTO teams (name, capacity) VALUES
    ('Бамбук', 10),
    ('Секвойи', 10),
    ('Баобабы', 10),
    ('Эвкалипты', 10)
ON CONFLICT (name) DO NOTHING;
