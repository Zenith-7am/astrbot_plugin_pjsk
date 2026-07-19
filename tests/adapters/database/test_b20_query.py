"""Tests for ScoreRepository B20 and difficulty-ranking query methods."""

import sqlite3
from datetime import datetime, timezone

import pytest_asyncio
from aiosqlite import Connection, connect

from adapters.database.repository import SqliteScoreRepository
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import UserId


NOW = datetime.now(timezone.utc).isoformat()


def _attempt(
    id_: int,
    user_id: int = 1,
    chart_id: int = 1,
    status: ScoreStatus = ScoreStatus.FC,
    rating: float = 30.0,
    accuracy: float = 99.0,
) -> ScoreAttempt:
    return ScoreAttempt(
        id=id_,
        user_id=UserId(user_id),
        chart_id=chart_id,
        judgements=Judgements(perfect=100, great=0, good=0, bad=0, miss=0),
        accuracy=accuracy,
        rating=rating,
        status=status,
        image_sha256="sha",
        source_gateway="test",
        ocr_run_id=None,
        created_at=datetime.now(timezone.utc),
    )


@pytest_asyncio.fixture
async def db() -> Connection:
    """In-memory SQLite with minimal schema for score queries."""
    conn = await connect(":memory:")
    conn.row_factory = sqlite3.Row
    await conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qq_number TEXT NOT NULL UNIQUE,
            game_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE songs (
            id INTEGER PRIMARY KEY,
            title_ja TEXT NOT NULL
        );
        CREATE TABLE charts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL REFERENCES songs(id),
            difficulty TEXT NOT NULL,
            official_level INTEGER NOT NULL,
            community_constant TEXT NOT NULL,
            note_count INTEGER NOT NULL,
            chart_data_version TEXT NOT NULL
        );
        CREATE TABLE score_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            chart_id INTEGER NOT NULL REFERENCES charts(id),
            perfect INTEGER NOT NULL,
            great INTEGER NOT NULL,
            good INTEGER NOT NULL,
            bad INTEGER NOT NULL,
            miss INTEGER NOT NULL,
            accuracy REAL NOT NULL,
            rating REAL NOT NULL,
            status TEXT NOT NULL,
            image_sha256 TEXT NOT NULL,
            source_gateway TEXT NOT NULL,
            ocr_run_id INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE personal_bests (
            user_id INTEGER NOT NULL REFERENCES users(id),
            chart_id INTEGER NOT NULL REFERENCES charts(id),
            best_attempt_id INTEGER NOT NULL REFERENCES score_attempts(id),
            accuracy REAL NOT NULL,
            rating REAL NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, chart_id)
        );
    """
    )
    await conn.commit()
    # Seed: user
    await conn.execute(
        "INSERT INTO users (id, qq_number, created_at, updated_at) VALUES (1, '1234567890', ?, ?)",
        (NOW, NOW),
    )
    # Seed: songs
    for sid in range(1, 5):
        await conn.execute("INSERT INTO songs (id, title_ja) VALUES (?, 'Test')", (sid,))
    # Seed: charts — mix of APPEND and non-APPEND
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (1, 1, 'master', 31, '31.0', 1000, 'v1')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (2, 2, 'master', 30, '30.0', 900, 'v1')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (3, 3, 'append', 31, '31.5', 1100, 'v1')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (4, 4, 'expert', 28, '28.0', 800, 'v1')"
    )
    # Seed: score_attempts + personal_bests for user 1
    # Chart 1 (master 31): FC, rating 33.0
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, good, bad, miss, accuracy, rating, status, image_sha256, source_gateway, created_at) "
        "VALUES (1, 1, 1, 1000, 0, 0, 0, 0, 99.5, 33.0, 'fc', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, accuracy, rating, status, updated_at) "
        "VALUES (1, 1, 1, 99.5, 33.0, 'fc', ?)",
        (NOW,),
    )
    # Chart 2 (master 30): FC, rating 29.0
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, good, bad, miss, accuracy, rating, status, image_sha256, source_gateway, created_at) "
        "VALUES (2, 1, 2, 900, 0, 0, 0, 0, 99.0, 29.0, 'fc', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, accuracy, rating, status, updated_at) "
        "VALUES (1, 2, 2, 99.0, 29.0, 'fc', ?)",
        (NOW,),
    )
    # Chart 3 (append 31): AP, rating 35.0 — this is APPEND
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, good, bad, miss, accuracy, rating, status, image_sha256, source_gateway, created_at) "
        "VALUES (3, 1, 3, 1100, 0, 0, 0, 0, 101.0, 35.0, 'ap', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, accuracy, rating, status, updated_at) "
        "VALUES (1, 3, 3, 101.0, 35.0, 'ap', ?)",
        (NOW,),
    )
    # Chart 4 (expert 28): CLEAR — should not appear in B20
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, good, bad, miss, accuracy, rating, status, image_sha256, source_gateway, created_at) "
        "VALUES (4, 1, 4, 800, 0, 0, 0, 0, 99.0, 27.0, 'clear', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, accuracy, rating, status, updated_at) "
        "VALUES (1, 4, 4, 99.0, 27.0, 'clear', ?)",
        (NOW,),
    )
    # ── Same-song MA+APD (song 5, chart 5/6) ────────────────────────────
    # Chart 5 (master 31, song 5): FC, rating 33.0
    # Chart 6 (append 32, song 5): AP, rating 35.0
    await conn.execute(
        "INSERT INTO songs (id, title_ja) VALUES (5, 'SameSong')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, "
        "community_constant, note_count, chart_data_version) "
        "VALUES (5, 5, 'master', 31, '31.0', 1000, 'v1')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, "
        "community_constant, note_count, chart_data_version) "
        "VALUES (6, 5, 'append', 32, '32.0', 1200, 'v1')"
    )
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, "
        "good, bad, miss, accuracy, rating, status, image_sha256, "
        "source_gateway, created_at) "
        "VALUES (5, 1, 5, 1000, 0, 0, 0, 0, 99.5, 33.0, 'fc', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, "
        "accuracy, rating, status, updated_at) "
        "VALUES (1, 5, 5, 99.5, 33.0, 'fc', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, "
        "good, bad, miss, accuracy, rating, status, image_sha256, "
        "source_gateway, created_at) "
        "VALUES (6, 1, 6, 1200, 0, 0, 0, 0, 101.0, 35.0, 'ap', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, "
        "accuracy, rating, status, updated_at) "
        "VALUES (1, 6, 6, 101.0, 35.0, 'ap', ?)",
        (NOW,),
    )
    # ── Same-song MA+EXP (song 6, chart 7/8) ────────────────────────────
    # Chart 7 (master 30, song 6): FC, rating 30.0
    # Chart 8 (expert 28, song 6): FC, rating 29.0
    await conn.execute(
        "INSERT INTO songs (id, title_ja) VALUES (6, 'MultiDiff')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, "
        "community_constant, note_count, chart_data_version) "
        "VALUES (7, 6, 'master', 30, '30.0', 900, 'v1')"
    )
    await conn.execute(
        "INSERT INTO charts (id, song_id, difficulty, official_level, "
        "community_constant, note_count, chart_data_version) "
        "VALUES (8, 6, 'expert', 28, '28.0', 800, 'v1')"
    )
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, "
        "good, bad, miss, accuracy, rating, status, image_sha256, "
        "source_gateway, created_at) "
        "VALUES (7, 1, 7, 900, 0, 0, 0, 0, 99.0, 30.0, 'fc', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, "
        "accuracy, rating, status, updated_at) "
        "VALUES (1, 7, 7, 99.0, 30.0, 'fc', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO score_attempts (id, user_id, chart_id, perfect, great, "
        "good, bad, miss, accuracy, rating, status, image_sha256, "
        "source_gateway, created_at) "
        "VALUES (8, 1, 8, 800, 0, 0, 0, 0, 98.0, 29.0, 'fc', 'sha', 'test', ?)",
        (NOW,),
    )
    await conn.execute(
        "INSERT INTO personal_bests (user_id, chart_id, best_attempt_id, "
        "accuracy, rating, status, updated_at) "
        "VALUES (1, 8, 8, 98.0, 29.0, 'fc', ?)",
        (NOW,),
    )
    await conn.commit()
    return conn


@pytest_asyncio.fixture
async def repo(db: Connection) -> SqliteScoreRepository:
    return SqliteScoreRepository(db)


class TestGetB20:
    async def test_returns_fc_ap_only(self, repo: SqliteScoreRepository) -> None:
        """B20 only includes FC and AP personal bests, not CLEAR."""
        rows = await repo.get_b20(UserId(1), include_append=True)
        statuses = {r.status for r in rows}
        assert ScoreStatus.CLEAR not in statuses
        assert statuses <= {ScoreStatus.AP, ScoreStatus.FC}

    async def test_sorted_by_rating_desc(self, repo: SqliteScoreRepository) -> None:
        """B20 results are sorted by rating DESC, chart_id ASC for ties."""
        rows = await repo.get_b20(UserId(1), include_append=True)
        for i in range(len(rows) - 1):
            assert rows[i].rating >= rows[i + 1].rating

    async def test_excludes_append_when_include_append_false(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """When include_append=False, APPEND charts are excluded from B20."""
        rows = await repo.get_b20(UserId(1), include_append=False)
        # Chart 3 (APPEND, id=3) should not appear
        chart_ids = {r.chart_id for r in rows}
        assert 3 not in chart_ids
        # Chart 1 and 2 (master) should appear
        assert 1 in chart_ids
        assert 2 in chart_ids

    async def test_includes_append_when_include_append_true(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """When include_append=True, APPEND charts are included in B20."""
        rows = await repo.get_b20(UserId(1), include_append=True)
        chart_ids = {r.chart_id for r in rows}
        assert 3 in chart_ids  # APPEND chart

    async def test_limits_to_20(self, repo: SqliteScoreRepository) -> None:
        """get_b20 returns at most 20 rows."""
        rows = await repo.get_b20(UserId(1), include_append=True)
        assert len(rows) <= 20

    async def test_no_personal_best_returns_empty(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """User with no scores returns empty list."""
        rows = await repo.get_b20(UserId(999), include_append=True)
        assert rows == []

    async def test_same_song_master_and_append_both_appear(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """Same song MA(FC,33.0) and APD(AP,35.0) both appear in B20
        when include_append=True. They must NOT be deduped into one entry."""
        rows = await repo.get_b20(UserId(1), include_append=True)
        chart_ids = {r.chart_id for r in rows}
        assert 5 in chart_ids   # MA of SameSong
        assert 6 in chart_ids   # APD of SameSong

    async def test_same_song_master_expert_still_deduped(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """Same song MA(FC,30.0) and EXP(FC,29.0): only MA appears.
        Non-APPEND difficulties still deduplicate by song_id."""
        rows = await repo.get_b20(UserId(1), include_append=True)
        chart_ids = {r.chart_id for r in rows}
        assert 7 in chart_ids   # MA of MultiDiff (rating 30.0 > 29.0)
        assert 8 not in chart_ids  # EXP should be deduped out


class TestListPersonalBestsForDifficulty:
    async def test_returns_dict_indexed_by_chart_id(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """Returns dict[int, ScoreAttempt] keyed by chart_id."""
        result = await repo.list_personal_bests_for_difficulty(
            UserId(1), [1, 2],
        )
        assert isinstance(result, dict)
        assert 1 in result
        assert result[1].chart_id == 1
        assert result[2].chart_id == 2

    async def test_missing_chart_not_in_dict(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """Charts with no personal best are absent from dict."""
        result = await repo.list_personal_bests_for_difficulty(
            UserId(1), [1, 999],
        )
        assert 1 in result
        assert 999 not in result

    async def test_empty_chart_ids_returns_empty_dict(
        self, repo: SqliteScoreRepository,
    ) -> None:
        """Empty input list returns empty dict."""
        result = await repo.list_personal_bests_for_difficulty(UserId(1), [])
        assert result == {}
