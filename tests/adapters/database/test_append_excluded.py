"""Tests for append_excluded user preference — migration, repository, domain."""

import sqlite3

import pytest
import pytest_asyncio
from aiosqlite import Connection, connect

from adapters.database.repository import SqliteUserRepository
from pjsk_core.domain.users import QqNumber, User, UserId


@pytest_asyncio.fixture
async def db() -> Connection:
    """In-memory SQLite with full initial schema (migrations 001-006)."""
    conn = await connect(":memory:")
    conn.row_factory = sqlite3.Row
    # 001: initial schema
    await conn.executescript(
        """
        CREATE TABLE users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            qq_number  TEXT NOT NULL UNIQUE,
            game_id    TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (length(qq_number) >= 5),
            CHECK (game_id IS NULL OR length(game_id) > 0)
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
            UNIQUE(song_id, difficulty),
            CHECK (difficulty IN ('easy','normal','hard','expert','master','append')),
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
    """
    )
    await conn.commit()
    # 006: append_excluded
    await conn.executescript(
        "ALTER TABLE users ADD COLUMN append_excluded INTEGER NOT NULL DEFAULT 1;"
    )
    await conn.commit()
    return conn


@pytest_asyncio.fixture
async def repo(db: Connection) -> SqliteUserRepository:
    return SqliteUserRepository(db)


@pytest_asyncio.fixture
async def user(repo: SqliteUserRepository) -> User:
    return await repo.create(QqNumber("1234567890"), None)


class TestAppendExcludedDomain:
    """Domain-level tests for append_excluded on User dataclass."""

    def test_user_defaults_append_excluded_to_true(self) -> None:
        """New User without explicit append_excluded defaults to True."""
        u = User(
            id=UserId(1),
            qq_number=QqNumber("1234567890"),
            game_id=None,
        )
        assert u.append_excluded is True

    def test_user_append_excluded_can_be_set_false(self) -> None:
        """append_excluded can be explicitly set to False."""
        u = User(
            id=UserId(1),
            qq_number=QqNumber("1234567890"),
            game_id=None,
            append_excluded=False,
        )
        assert u.append_excluded is False

    def test_user_is_still_frozen(self) -> None:
        """User remains frozen with append_excluded."""
        u = User(id=UserId(1), qq_number=QqNumber("1234567890"), game_id=None)
        with pytest.raises(Exception):
            u.append_excluded = False  # type: ignore[misc]


class TestAppendExcludedRepository:
    """Repository-level tests for get/set append_excluded."""

    async def test_new_user_has_append_excluded_true(
        self, repo: SqliteUserRepository, user: User,
    ) -> None:
        """Newly created user defaults to append_excluded = True."""
        result = await repo.get_append_excluded(user.id)
        assert result is True

    async def test_set_append_excluded_to_false(
        self, repo: SqliteUserRepository, user: User,
    ) -> None:
        """set_append_excluded(False) toggles preference."""
        await repo.set_append_excluded(user.id, False)
        result = await repo.get_append_excluded(user.id)
        assert result is False

    async def test_set_append_excluded_back_to_true(
        self, repo: SqliteUserRepository, user: User,
    ) -> None:
        """Toggling back to True works."""
        await repo.set_append_excluded(user.id, False)
        await repo.set_append_excluded(user.id, True)
        result = await repo.get_append_excluded(user.id)
        assert result is True

    async def test_user_object_reflects_append_excluded(
        self, repo: SqliteUserRepository, user: User,
    ) -> None:
        """After reading user back, append_excluded is present."""
        fetched = await repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.append_excluded is True

    async def test_backfill_user_with_append_fc_gets_excluded_false(
        self, db: Connection, repo: SqliteUserRepository,
    ) -> None:
        """Migration backfill: user with APPEND FC gets append_excluded=0."""
        # Create user
        user = await repo.create(QqNumber("9876543210"), None)
        # Insert song + chart (APPEND difficulty)
        await db.execute("INSERT INTO songs (id, title_ja) VALUES (1, 'Test')")
        await db.execute(
            "INSERT INTO charts (id, song_id, difficulty, official_level, "
            "community_constant, note_count, chart_data_version) "
            "VALUES (1, 1, 'append', 30, '30.0', 1000, 'v1')"
        )
        # Insert score_attempt + personal_best (AP on APPEND)
        now = "2026-07-14T00:00:00"
        await db.execute(
            "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, "
            "good, bad, miss, accuracy, rating, status, image_sha256, "
            "source_gateway, created_at) "
            "VALUES (1, ?, 1, 1000, 0, 0, 0, 0, 101.0, 30.0, 'ap', 'sha', 'test', ?)",
            (user.id.value, now),
        )
        await db.execute(
            "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, "
            "accuracy, rating, status, updated_at) "
            "VALUES (?, 1, 1, 101.0, 30.0, 'ap', ?)",
            (user.id.value, now),
        )
        await db.commit()
        # Simulate backfill UPDATE from migration
        await db.execute(
            "UPDATE users SET append_excluded = 0 "
            "WHERE id IN ("
            "  SELECT DISTINCT pb.user_id FROM personal_bests pb "
            "  JOIN charts c ON c.id = pb.chart_id "
            "  WHERE c.difficulty = 'append' AND pb.status IN ('ap', 'fc')"
            ")"
        )
        await db.commit()
        result = await repo.get_append_excluded(user.id)
        assert result is False
