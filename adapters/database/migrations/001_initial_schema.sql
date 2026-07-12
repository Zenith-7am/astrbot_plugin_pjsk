-- 001: Initial schema — users, songs, charts, scores, personal_bests

CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qq_number  TEXT NOT NULL UNIQUE,
    game_id    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (length(qq_number) >= 5),
    CHECK (game_id IS NULL OR length(game_id) > 0)
);

CREATE TABLE external_identities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    platform    TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(platform, external_id),
    CHECK (length(platform) > 0),
    CHECK (length(external_id) > 0)
);

CREATE TABLE songs (
    id       INTEGER PRIMARY KEY,
    title_ja TEXT NOT NULL,
    title_cn TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT '',
    CHECK (length(title_ja) > 0)
);

CREATE TABLE charts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id            INTEGER NOT NULL REFERENCES songs(id),
    difficulty         TEXT NOT NULL,
    official_level     INTEGER NOT NULL,
    community_constant TEXT NOT NULL,
    note_count         INTEGER NOT NULL,
    chart_data_version TEXT NOT NULL,
    UNIQUE(song_id, difficulty),
    CHECK (difficulty IN ('easy', 'normal', 'hard', 'expert', 'master', 'append')),
    CHECK (official_level > 0),
    CHECK (note_count > 0)
);

CREATE TABLE score_attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    chart_id       INTEGER NOT NULL REFERENCES charts(id),
    perfect        INTEGER NOT NULL,
    great          INTEGER NOT NULL,
    good           INTEGER NOT NULL,
    bad            INTEGER NOT NULL,
    miss           INTEGER NOT NULL,
    accuracy       REAL NOT NULL,
    rating         REAL NOT NULL,
    status         TEXT NOT NULL,
    image_sha256   TEXT NOT NULL,
    source_gateway TEXT NOT NULL,
    ocr_run_id     INTEGER,
    created_at     TEXT NOT NULL,
    CHECK (perfect >= 0),
    CHECK (great >= 0),
    CHECK (good >= 0),
    CHECK (bad >= 0),
    CHECK (miss >= 0),
    CHECK (accuracy >= 0),
    CHECK (rating >= 0),
    CHECK (status IN ('ap', 'fc', 'clear'))
);

CREATE TABLE personal_bests (
    user_id         INTEGER NOT NULL REFERENCES users(id),
    chart_id        INTEGER NOT NULL REFERENCES charts(id),
    best_attempt_id INTEGER NOT NULL REFERENCES score_attempts(id),
    accuracy        REAL NOT NULL,
    rating          REAL NOT NULL,
    status          TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY(user_id, chart_id),
    CHECK (accuracy >= 0),
    CHECK (rating >= 0),
    CHECK (status IN ('ap', 'fc', 'clear'))
);
