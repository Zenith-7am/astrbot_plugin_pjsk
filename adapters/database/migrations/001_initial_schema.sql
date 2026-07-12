-- 001: Initial schema — users, songs, charts, scores, personal_bests

CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qq_number  TEXT NOT NULL UNIQUE,
    game_id    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE external_identities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    platform    TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE TABLE songs (
    id       INTEGER PRIMARY KEY,
    title_ja TEXT NOT NULL,
    title_cn TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT ''
);

CREATE TABLE charts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id            INTEGER NOT NULL REFERENCES songs(id),
    difficulty         TEXT NOT NULL,
    official_level     INTEGER NOT NULL,
    community_constant TEXT NOT NULL,
    note_count         INTEGER NOT NULL,
    chart_data_version TEXT NOT NULL,
    UNIQUE(song_id, difficulty)
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
    created_at     TEXT NOT NULL
);

CREATE TABLE personal_bests (
    user_id         INTEGER NOT NULL REFERENCES users(id),
    chart_id        INTEGER NOT NULL REFERENCES charts(id),
    best_attempt_id INTEGER NOT NULL REFERENCES score_attempts(id),
    accuracy        REAL NOT NULL,
    rating          REAL NOT NULL,
    status          TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY(user_id, chart_id)
);
