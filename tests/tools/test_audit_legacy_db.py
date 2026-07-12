"""Tests for tools.audit_legacy_db — synthetic legacy database fixtures."""

import hashlib
import sqlite3
import time
from pathlib import Path

import pytest
from tools.audit_legacy_db import audit_database


# ── Synthetic legacy database fixture ────────────────────────────────


def _build_legacy_db(path: Path) -> None:
    """Build a synthetic database matching the old emu-bot schema."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # users (qq_id TEXT PK, game_id TEXT, …, created_at/updated_at INTEGER)
    conn.execute("""
        CREATE TABLE users (
            qq_id      TEXT PRIMARY KEY,
            game_id    TEXT,
            b20_cache_path TEXT DEFAULT '',
            a39_cache_path TEXT DEFAULT '',
            append_excluded INTEGER DEFAULT 1,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # scores (UNIQUE on game_id, song_id, difficulty)
    conn.execute("""
        CREATE TABLE scores (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id    TEXT NOT NULL,
            song_id    INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            perfect    INTEGER DEFAULT 0,
            great      INTEGER DEFAULT 0,
            good       INTEGER DEFAULT 0,
            bad        INTEGER DEFAULT 0,
            miss       INTEGER DEFAULT 0,
            accuracy   REAL DEFAULT 0,
            power      REAL DEFAULT 0,
            uploaded_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX idx_scores_unique
        ON scores(game_id, song_id, difficulty)
    """)

    # score_history
    conn.execute("""
        CREATE TABLE score_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id    TEXT NOT NULL,
            song_id    INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            perfect    INTEGER DEFAULT 0,
            great      INTEGER DEFAULT 0,
            good       INTEGER DEFAULT 0,
            bad        INTEGER DEFAULT 0,
            miss       INTEGER DEFAULT 0,
            accuracy   REAL DEFAULT 0,
            power      REAL DEFAULT 0,
            uploaded_at INTEGER NOT NULL
        )
    """)

    # songs
    conn.execute("""
        CREATE TABLE songs (
            id        INTEGER PRIMARY KEY,
            title_ja  TEXT NOT NULL,
            title_cn  TEXT DEFAULT '',
            title_en  TEXT DEFAULT '',
            aliases   TEXT DEFAULT '[]'
        )
    """)

    # song_difficulties
    conn.execute("""
        CREATE TABLE song_difficulties (
            song_id    INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            note_count INTEGER DEFAULT 0,
            constant   REAL DEFAULT 0,
            const_tag  TEXT DEFAULT '',
            PRIMARY KEY (song_id, difficulty)
        )
    """)

    # ocr_records
    conn.execute("""
        CREATE TABLE ocr_records (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            qq_id      TEXT NOT NULL,
            ocr_lines  TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)

    now = int(time.time())

    # ── Insert normal data ──
    # scores.game_id is the QQ number in the legacy schema
    conn.execute(
        "INSERT INTO users(qq_id, game_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("111111", "pid_a", now - 86400, now),
    )
    conn.execute(
        "INSERT INTO users(qq_id, game_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("222222", "pid_b", now - 172800, now - 3600),
    )
    # Duplicate PJSK game_id (same pid assigned to two QQ)
    conn.execute(
        "INSERT INTO users(qq_id, game_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("333333", "pid_a", now, now),
    )
    # Null PJSK game_id
    conn.execute(
        "INSERT INTO users(qq_id, game_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("444444", None, now, now),
    )

    # Scores — game_id field is actually QQ number
    conn.execute(
        "INSERT INTO scores(game_id, song_id, difficulty, perfect, great, good, bad, miss, accuracy, power, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("111111", 1, "master", 1000, 0, 0, 0, 0, 101.0, 3100.0, now),
    )
    conn.execute(
        "INSERT INTO scores(game_id, song_id, difficulty, perfect, great, good, bad, miss, accuracy, power, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("111111", 2, "expert", 900, 100, 0, 0, 0, 100.5, 2800.0, now - 3600),
    )
    # Orphan score — QQ number not in users
    conn.execute(
        "INSERT INTO scores(game_id, song_id, difficulty, perfect, great, good, bad, miss, accuracy, power, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("999999", 3, "hard", 500, 0, 0, 0, 0, 80.0, 1000.0, now),
    )
    # Invalid score — negative perfect
    conn.execute(
        "INSERT INTO scores(game_id, song_id, difficulty, perfect, great, good, bad, miss, accuracy, power, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("222222", 1, "master", -1, 0, 0, 0, 0, 0.0, 0.0, now),
    )

    # Song data
    conn.execute("INSERT INTO songs(id, title_ja, title_cn) VALUES (?, ?, ?)", (1, "テスト", "测试"))
    conn.execute("INSERT INTO songs(id, title_ja, title_cn) VALUES (?, ?, ?)", (2, "曲2", "歌2"))
    conn.execute("INSERT INTO song_difficulties(song_id, difficulty, note_count, constant, const_tag) VALUES (?, ?, ?, ?, ?)", (1, "master", 1200, 30.0, ""))

    conn.commit()
    conn.close()


# ── Tests ─────────────────────────────────────────────────────────────


class TestAuditDatabase:
    def test_reports_table_counts(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert report.tables["users"] == 4
        assert report.tables["scores"] == 4
        assert report.tables["score_history"] == 0
        assert report.tables["songs"] == 2
        assert report.tables["song_difficulties"] == 1
        assert report.tables["ocr_records"] == 0

    def test_reports_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert "qq_id" in report.columns["users"]
        assert "game_id" in report.columns["users"]
        assert "perfect" in report.columns["scores"]

    def test_detects_duplicate_game_ids(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        # player_a appears for both 111111 and 333333
        assert report.duplicate_game_ids == 1  # "player_a" is duplicated

    def test_detects_orphan_scores(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert report.orphan_scores == 1  # orphan_player not in users

    def test_detects_null_identities(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert report.null_identity_count == 1  # 444444 has game_id=NULL

    def test_detects_invalid_scores(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert report.invalid_scores >= 1  # negative perfect count

    def test_reports_timestamps(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert report.min_timestamp is not None
        assert report.max_timestamp is not None
        assert report.min_timestamp <= report.max_timestamp

    def test_read_only_does_not_modify(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        mtime_before = db.stat().st_mtime
        original_hash = hashlib.sha256(db.read_bytes()).hexdigest()

        audit_database(db)

        assert db.stat().st_mtime == mtime_before
        assert hashlib.sha256(db.read_bytes()).hexdigest() == original_hash

    def test_reports_source_sha256(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        assert len(report.source_sha256) == 64  # SHA-256 hex digest

    def test_never_emits_qq_numbers(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        output = str(report.tables) + str(report.columns) + str(report.__dict__)
        assert "111111" not in output
        assert "222222" not in output
        assert "333333" not in output
        assert "444444" not in output

    def test_never_emits_row_values(self, tmp_path: Path) -> None:
        """Column names (schema) are fine; actual user data must never leak."""
        db = tmp_path / "legacy.db"
        _build_legacy_db(db)
        report = audit_database(db)
        output = str(report.__dict__)
        # PJSK game IDs must never appear
        assert "pid_a" not in output
        assert "pid_b" not in output
        # QQ numbers must never appear
        assert "111111" not in output
        assert "222222" not in output


class TestMissingSchema:
    def test_missing_required_table_exits_nonzero(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE irrelevant (x INTEGER)")
        conn.commit()
        conn.close()
        with pytest.raises(SystemExit) as exc:
            audit_database(db)
        assert exc.value.code != 0


class TestUnrecognizedTables:
    def test_extra_tables_do_not_crash(self, tmp_path: Path) -> None:
        db = tmp_path / "extra.db"
        _build_legacy_db(db)
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE custom_plugin_data (key TEXT, val TEXT)")
        conn.commit()
        conn.close()
        report = audit_database(db)
        assert "custom_plugin_data" in report.unrecognized_tables
        assert report.tables.get("users", 0) > 0  # core tables still audited
