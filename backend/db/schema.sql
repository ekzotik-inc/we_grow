-- We Grow — схема БД (PostgreSQL). MVP.
-- Времена дней считаются в TZ марафона (см. backend/config).

CREATE TABLE teams (
    id       serial PRIMARY KEY,
    name     text NOT NULL UNIQUE,
    capacity int  NOT NULL DEFAULT 10
);

CREATE TABLE participants (
    telegram_id     bigint PRIMARY KEY,
    full_name       text        NOT NULL,
    is_asr          boolean     NOT NULL DEFAULT false,
    team_id         int         REFERENCES teams(id),
    role            text        NOT NULL DEFAULT 'participant',  -- participant | admin
    consent_at      timestamptz,                                 -- согласие с правилами (п.6)
    disqualified_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX participants_team_idx ON participants(team_id);

CREATE TABLE daily_entries (
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

CREATE INDEX daily_review_idx ON daily_entries(needs_review) WHERE needs_review;

CREATE TABLE streaks (
    participant_id        bigint PRIMARY KEY REFERENCES participants(telegram_id),
    current_len           int  NOT NULL DEFAULT 0,   -- дней подряд по 10 000+
    last_qualifying_date  date,
    bonus_awarded_cycles  int  NOT NULL DEFAULT 0    -- сколько раз начислен +4 за 7 дней
);

CREATE TABLE weekly_summaries (
    id                 bigserial PRIMARY KEY,
    participant_id     bigint  NOT NULL REFERENCES participants(telegram_id),
    week_start         date    NOT NULL,
    reported_total     int     NOT NULL,
    computed_total     int     NOT NULL,
    reconciled         boolean NOT NULL DEFAULT false,
    screenshot_file_id text,
    UNIQUE (participant_id, week_start)
);

CREATE TABLE broadcasts (
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
    ('Эвкалипты', 10);
