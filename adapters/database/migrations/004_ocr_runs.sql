-- 004: OCR run audit tables — one row per recognition attempt + per-engine observations

CREATE TABLE ocr_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_sha256    TEXT NOT NULL CHECK (length(image_sha256) = 64),
    source_gateway  TEXT NOT NULL CHECK (length(source_gateway) > 0),
    final_state     TEXT NOT NULL CHECK (
        final_state IN (
            'consensus', 'degraded_single', 'disagreement',
            'all_failed', 'no_available_engines', 'global_timeout'
        )
    ),
    selected_engine TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_ocr_runs_user_created ON ocr_runs(user_id, created_at);

CREATE TABLE ocr_observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_run_id        INTEGER NOT NULL REFERENCES ocr_runs(id) ON DELETE CASCADE,
    engine_id         TEXT NOT NULL,
    provider          TEXT NOT NULL CHECK (length(provider) > 0),
    result_status     TEXT NOT NULL CHECK (
        result_status IN (
            'success', 'failed', 'timed_out',
            'cancelled_by_consensus', 'cancelled_by_caller', 'circuit_rejected'
        )
    ),
    elapsed_ms        INTEGER NOT NULL CHECK (elapsed_ms >= 0),
    song_title        TEXT,
    difficulty        TEXT CHECK (difficulty IS NULL OR difficulty IN (
        'easy', 'normal', 'hard', 'expert', 'master', 'append'
    )),
    displayed_level   INTEGER,
    perfect           INTEGER CHECK (perfect IS NULL OR perfect >= 0),
    great             INTEGER CHECK (great IS NULL OR great >= 0),
    good              INTEGER CHECK (good IS NULL OR good >= 0),
    bad               INTEGER CHECK (bad IS NULL OR bad >= 0),
    miss              INTEGER CHECK (miss IS NULL OR miss >= 0),
    matched_chart_id  INTEGER REFERENCES charts(id),
    validation_status TEXT CHECK (validation_status IS NULL OR validation_status IN (
        'strong', 'candidate', 'rejected'
    )),
    error_type        TEXT CHECK (error_type IS NULL OR error_type IN (
        'timeout', 'connection', 'rate_limited',
        'server_error', 'invalid_response'
    )),
    UNIQUE(ocr_run_id, engine_id)
);

CREATE INDEX idx_ocr_obs_run ON ocr_observations(ocr_run_id);
