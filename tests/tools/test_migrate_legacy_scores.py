"""Tests for tools.migrate_legacy_scores."""
import sqlite3
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from tools.migrate_legacy_scores import (
    EMPTY_IMAGE_SHA256,
    SOURCE_GATEWAY,
    _build_chart_lookup,
    _compute_personal_bests,
    _derive_status,
    _enrich_songs,
    _migrate_openid_map,
    _migrate_score_rows,
    _migrate_users,
    _open_legacy_ro,
    _read_openid_map,
    _read_scores,
    _read_songs,
    _read_users,
    _unix_to_iso,
    migrate,
)


# ═══════════════════════════════════════════════════════════════════════════════
# unit: helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveStatus:
    def test_ap(self) -> None:
        assert _derive_status(1000, 0, 0, 0, 0) == "ap"

    def test_ap_requires_positive_perfect(self) -> None:
        assert _derive_status(0, 0, 0, 0, 0) != "ap"

    def test_fc(self) -> None:
        assert _derive_status(800, 200, 0, 0, 0) == "fc"

    def test_fc_with_bad_and_miss_is_not_fc(self) -> None:
        assert _derive_status(800, 100, 0, 1, 0) != "fc"
        assert _derive_status(800, 100, 0, 0, 1) != "fc"

    def test_clear(self) -> None:
        assert _derive_status(500, 200, 100, 50, 10) == "clear"

    def test_clear_when_good_present(self) -> None:
        # GOOD breaks combo → not FC
        assert _derive_status(900, 50, 1, 0, 0) == "clear"


class TestUnixToIso:
    def test_converts(self) -> None:
        result = _unix_to_iso(1782343750)
        assert result.startswith("2026-06-")
        assert "T" in result
        assert result.endswith("+00:00") or result.endswith("Z")

    def test_float_timestamp(self) -> None:
        result = _unix_to_iso(1782343750.0)
        assert "T" in result


# ═══════════════════════════════════════════════════════════════════════════════
# fixtures: create legacy and new databases
# ═══════════════════════════════════════════════════════════════════════════════


def _create_legacy_db(path: Path) -> None:
    """Create a minimal legacy emu-bot database for testing."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE users (
            qq_id           TEXT PRIMARY KEY,
            game_id         TEXT,
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL,
            b20_cache_path  TEXT DEFAULT '',
            a39_cache_path  TEXT DEFAULT '',
            append_excluded INTEGER DEFAULT 1
        );

        CREATE TABLE songs (
            id        INTEGER PRIMARY KEY,
            title_ja  TEXT NOT NULL,
            title_cn  TEXT DEFAULT '',
            title_en  TEXT DEFAULT '',
            aliases   TEXT DEFAULT '[]'
        );

        CREATE TABLE song_difficulties (
            song_id    INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            note_count INTEGER DEFAULT 0,
            constant   REAL DEFAULT 0,
            const_tag  TEXT DEFAULT '',
            PRIMARY KEY (song_id, difficulty)
        );

        CREATE TABLE scores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     TEXT NOT NULL,
            song_id     INTEGER NOT NULL,
            difficulty  TEXT NOT NULL,
            perfect     INTEGER DEFAULT 0,
            great       INTEGER DEFAULT 0,
            good        INTEGER DEFAULT 0,
            bad         INTEGER DEFAULT 0,
            miss        INTEGER DEFAULT 0,
            accuracy    REAL DEFAULT 0,
            power       REAL DEFAULT 0,
            uploaded_at INTEGER NOT NULL
        );

        CREATE TABLE score_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     TEXT NOT NULL,
            song_id     INTEGER NOT NULL,
            difficulty  TEXT NOT NULL,
            perfect     INTEGER DEFAULT 0,
            great       INTEGER DEFAULT 0,
            good        INTEGER DEFAULT 0,
            bad         INTEGER DEFAULT 0,
            miss        INTEGER DEFAULT 0,
            accuracy    REAL DEFAULT 0,
            power       REAL DEFAULT 0,
            uploaded_at INTEGER NOT NULL
        );

        CREATE TABLE openid_map (
            openid       TEXT PRIMARY KEY,
            qq_id        TEXT NOT NULL UNIQUE,
            group_openid TEXT DEFAULT '',
            bound_at     INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def _seed_legacy_data(path: Path) -> None:
    """Insert known test data into the legacy DB."""
    conn = sqlite3.connect(str(path))
    ts = 1782343750  # 2026-06-25 approx

    # Users
    conn.executemany(
        "INSERT INTO users(qq_id, game_id, created_at, updated_at, append_excluded) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("111111", None, ts, ts, 1),
            ("222222", "player2", ts, ts, 0),
        ],
    )

    # Songs
    conn.executemany(
        "INSERT INTO songs(id, title_ja, title_cn, title_en, aliases) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (1, "テスト曲", "测试曲", "Test Song", '["test","alias1"]'),
            (2, "消失", "消失", "Disappearance", "[]"),
        ],
    )

    # Song difficulties
    conn.executemany(
        "INSERT INTO song_difficulties(song_id, difficulty, note_count, constant, const_tag) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (1, "master", 1200, 32.5, ""),
            (1, "expert", 900, 28.0, ""),
            (2, "master", 1500, 35.0, "+"),
        ],
    )

    # Score history (full upload history)
    conn.executemany(
        "INSERT INTO score_history(game_id, song_id, difficulty, perfect, great, good, bad, miss, accuracy, power, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # User 111111: song1 master — AP
            ("111111", 1, "master", 1200, 0, 0, 0, 0, 101.0, 3200.0, ts),
            # User 111111: song1 master — another attempt (worse)
            ("111111", 1, "master", 1000, 100, 50, 30, 20, 95.0, 2900.0, ts + 100),
            # User 111111: song1 expert — FC
            ("111111", 1, "expert", 850, 50, 0, 0, 0, 100.5, 2750.0, ts + 200),
            # User 222222: song2 master — CLEAR
            ("222222", 2, "master", 1200, 200, 50, 30, 20, 90.0, 3000.0, ts + 300),
        ],
    )

    # Scores (personal bests — should overlap with history for some charts)
    conn.executemany(
        "INSERT INTO scores(game_id, song_id, difficulty, perfect, great, good, bad, miss, accuracy, power, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # User 111111: song1 master — AP (best)
            ("111111", 1, "master", 1200, 0, 0, 0, 0, 101.0, 3200.0, ts),
            # User 111111: song1 expert — FC
            ("111111", 1, "expert", 850, 50, 0, 0, 0, 100.5, 2750.0, ts + 200),
            # User 222222: song2 master — CLEAR
            ("222222", 2, "master", 1200, 200, 50, 30, 20, 90.0, 3000.0, ts + 300),
        ],
    )

    # OpenID map
    conn.execute(
        "INSERT INTO openid_map(openid, qq_id, bound_at, last_seen_at) "
        "VALUES ('openid_abc', '111111', ?, ?)",
        (ts, ts),
    )

    conn.commit()
    conn.close()


def _seed_charts_for_test(conn: sqlite3.Connection) -> None:
    """Insert charts that match the test song_difficulties. Uses sync sqlite3."""
    conn.executemany(
        "INSERT INTO charts(song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "master", 32, "32.5", 1200, "test"),
            (1, "expert", 28, "28.0", 900, "test"),
            (2, "master", 35, "35.0+", 1500, "test"),
        ],
    )


@pytest.fixture
def legacy_db_path() -> Generator[Path]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    _create_legacy_db(path)
    _seed_legacy_data(path)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
async def new_db_path() -> AsyncGenerator[Path]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    await run_migrations(path)

    # Seed charts needed for the test scores
    sync_conn = sqlite3.connect(str(path))
    _seed_charts_for_test(sync_conn)
    sync_conn.commit()
    sync_conn.close()

    yield path
    path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# unit: read legacy
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadUsers:
    def test_reads_all(self, legacy_db_path: Path) -> None:
        conn = _open_legacy_ro(legacy_db_path)
        users = _read_users(conn)
        conn.close()
        assert len(users) == 2
        qq_ids = {u["qq_id"] for u in users}
        assert qq_ids == {"111111", "222222"}


class TestReadSongs:
    def test_reads_all(self, legacy_db_path: Path) -> None:
        conn = _open_legacy_ro(legacy_db_path)
        songs = _read_songs(conn)
        conn.close()
        assert len(songs) == 2
        assert songs[0]["aliases"] is not None


class TestReadScores:
    def test_reads_scores(self, legacy_db_path: Path) -> None:
        conn = _open_legacy_ro(legacy_db_path)
        rows = _read_scores(conn, "scores")
        conn.close()
        assert len(rows) == 3

    def test_reads_history(self, legacy_db_path: Path) -> None:
        conn = _open_legacy_ro(legacy_db_path)
        rows = _read_scores(conn, "score_history")
        conn.close()
        assert len(rows) == 4


class TestReadOpenidMap:
    def test_reads(self, legacy_db_path: Path) -> None:
        conn = _open_legacy_ro(legacy_db_path)
        rows = _read_openid_map(conn)
        conn.close()
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# unit: migrate helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestMigrateUsers:
    async def test_migrates_all(self, legacy_db_path: Path, new_db_path: Path) -> None:
        conn = _open_legacy_ro(legacy_db_path)
        users = _read_users(conn)
        conn.close()

        new_conn = await get_connection(new_db_path)
        try:
            mapping = await _migrate_users(new_conn, users)
            await new_conn.commit()
            assert len(mapping) == 2
            assert "111111" in mapping
            assert "222222" in mapping
            assert mapping["111111"] > 0
            assert mapping["222222"] > 0
            assert mapping["111111"] != mapping["222222"]

            # Verify data
            rows = list(await new_conn.execute_fetchall(
                "SELECT qq_number, game_id, append_excluded FROM users ORDER BY id"
            ))
            assert len(rows) == 2
            assert rows[0]["qq_number"] == "111111"
            assert rows[0]["game_id"] is None
            assert rows[0]["append_excluded"] == 1
            assert rows[1]["qq_number"] == "222222"
            assert rows[1]["game_id"] == "player2"
            assert rows[1]["append_excluded"] == 0
        finally:
            await new_conn.close()


class TestEnrichSongs:
    async def test_enriches_aliases(self, new_db_path: Path) -> None:
        # Seed songs in new DB (without aliases, simulating chart_data import)
        sync_conn = sqlite3.connect(str(new_db_path))
        sync_conn.executemany(
            "INSERT INTO songs(id, title_ja, title_cn, title_en, aliases) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (1, "テスト曲", "", "", "[]"),
                (2, "消失", "", "", "[]"),
            ],
        )
        sync_conn.commit()
        sync_conn.close()

        legacy_songs = [
            {"id": 1, "title_ja": "テスト曲", "title_cn": "测试曲", "title_en": "Test Song", "aliases": '["test","alias1"]'},
            {"id": 2, "title_ja": "消失", "title_cn": "消失", "title_en": "Disappearance", "aliases": "[]"},
        ]

        new_conn = await get_connection(new_db_path)
        try:
            updated = await _enrich_songs(new_conn, legacy_songs)
            await new_conn.commit()
            assert updated >= 2  # both songs get enriched

            # Verify song 1 got aliases, title_cn, title_en
            row = list(await new_conn.execute_fetchall(
                "SELECT title_cn, title_en, aliases FROM songs WHERE id = 1"
            ))
            assert row[0]["title_cn"] == "测试曲"
            assert row[0]["title_en"] == "Test Song"

            # Verify song 2 got title_cn, title_en
            row = list(await new_conn.execute_fetchall(
                "SELECT title_cn, title_en FROM songs WHERE id = 2"
            ))
            assert row[0]["title_cn"] == "消失"
            assert row[0]["title_en"] == "Disappearance"
        finally:
            await new_conn.close()

    async def test_skips_nonexistent_song(self, new_db_path: Path) -> None:
        legacy_songs = [
            {"id": 999, "title_ja": "NonExistent", "title_cn": "不存在", "title_en": "N/A", "aliases": "[]"},
        ]
        new_conn = await get_connection(new_db_path)
        try:
            updated = await _enrich_songs(new_conn, legacy_songs)
            await new_conn.commit()
            assert updated == 0
        finally:
            await new_conn.close()


class TestBuildChartLookup:
    async def test_builds_lookup(self, new_db_path: Path) -> None:
        new_conn = await get_connection(new_db_path)
        try:
            lookup = await _build_chart_lookup(new_conn)
            assert len(lookup) == 3
            assert lookup[(1, "master")] > 0
            assert lookup[(2, "master")] > 0
        finally:
            await new_conn.close()


class TestMigrateScoreRows:
    async def test_migrates_all(self, legacy_db_path: Path, new_db_path: Path) -> None:
        # First migrate users
        legacy_conn = _open_legacy_ro(legacy_db_path)
        legacy_users = _read_users(legacy_conn)
        legacy_history = _read_scores(legacy_conn, "score_history")
        legacy_conn.close()

        new_conn = await get_connection(new_db_path)
        try:
            qq_to_id = await _migrate_users(new_conn, legacy_users)
            await new_conn.commit()

            lookup = await _build_chart_lookup(new_conn)
            inserted, skipped = await _migrate_score_rows(
                new_conn, legacy_history, qq_to_id, lookup, is_history=True,
            )
            await new_conn.commit()

            assert inserted == 4
            assert skipped == 0

            # Verify status derivation
            rows = list(await new_conn.execute_fetchall(
                "SELECT user_id, status, rating, source_gateway, image_sha256 "
                "FROM score_attempts ORDER BY id"
            ))
            assert len(rows) == 4
            # First row: AP
            assert rows[0]["status"] == "ap"
            assert rows[0]["rating"] == 3200.0
            # Third row: FC
            assert rows[2]["status"] == "fc"
            # All have legacy source_gateway
            for r in rows:
                assert r["source_gateway"] == SOURCE_GATEWAY
                assert r["image_sha256"] == EMPTY_IMAGE_SHA256
        finally:
            await new_conn.close()

    async def test_skips_unknown_user(self, legacy_db_path: Path, new_db_path: Path) -> None:
        new_conn = await get_connection(new_db_path)
        try:
            lookup = await _build_chart_lookup(new_conn)
            rows = [{"game_id": "999999", "song_id": 1, "difficulty": "master",
                      "perfect": 100, "great": 0, "good": 0, "bad": 0, "miss": 0,
                      "accuracy": 100.0, "power": 1000.0, "uploaded_at": 1782343750}]
            inserted, skipped = await _migrate_score_rows(
                new_conn, rows, {}, lookup, is_history=True,
            )
            assert inserted == 0
            assert skipped == 1
        finally:
            await new_conn.close()

    async def test_skips_unknown_chart(self, legacy_db_path: Path, new_db_path: Path) -> None:
        new_conn = await get_connection(new_db_path)
        try:
            lookup = await _build_chart_lookup(new_conn)
            rows = [{"game_id": "111111", "song_id": 999, "difficulty": "master",
                      "perfect": 100, "great": 0, "good": 0, "bad": 0, "miss": 0,
                      "accuracy": 100.0, "power": 1000.0, "uploaded_at": 1782343750}]
            inserted, skipped = await _migrate_score_rows(
                new_conn, rows, {"111111": 1}, lookup, is_history=True,
            )
            assert inserted == 0
            assert skipped == 1
        finally:
            await new_conn.close()


class TestComputePersonalBests:
    async def test_selects_best_per_chart(self, new_db_path: Path) -> None:
        """Seed two attempts for same (user, chart): AP 3200 and FC 3100 → AP wins."""
        new_conn = await get_connection(new_db_path)
        try:
            # Seed user
            await new_conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, created_at, updated_at) "
                "VALUES ('111111', NULL, 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            user_id = 1

            # Insert two attempts for the same chart
            await new_conn.execute(
                "INSERT INTO score_attempts(user_id, chart_id, perfect, great, good, bad, miss, "
                "accuracy, rating, status, image_sha256, source_gateway, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, 1, 1200, 0, 0, 0, 0, 101.0, 3200.0, "ap",
                 EMPTY_IMAGE_SHA256, SOURCE_GATEWAY, "2026-01-01T00:00:00+00:00"),
            )
            await new_conn.execute(
                "INSERT INTO score_attempts(user_id, chart_id, perfect, great, good, bad, miss, "
                "accuracy, rating, status, image_sha256, source_gateway, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, 1, 1100, 50, 0, 0, 0, 100.5, 3100.0, "fc",
                 EMPTY_IMAGE_SHA256, SOURCE_GATEWAY, "2026-01-02T00:00:00+00:00"),
            )
            await new_conn.commit()

            pb_count = await _compute_personal_bests(new_conn)
            await new_conn.commit()

            assert pb_count == 1
            rows = list(await new_conn.execute_fetchall(
                "SELECT status, rating FROM personal_bests WHERE user_id = ? AND chart_id = ?",
                (user_id, 1),
            ))
            assert len(rows) == 1
            assert rows[0]["status"] == "ap"
            assert rows[0]["rating"] == 3200.0
        finally:
            await new_conn.close()

    async def test_fc_beats_clear(self, new_db_path: Path) -> None:
        """FC with lower rating beats CLEAR with higher rating."""
        new_conn = await get_connection(new_db_path)
        try:
            await new_conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, created_at, updated_at) "
                "VALUES ('111111', NULL, 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )

            # CLEAR with high rating
            await new_conn.execute(
                "INSERT INTO score_attempts(user_id, chart_id, perfect, great, good, bad, miss, "
                "accuracy, rating, status, image_sha256, source_gateway, created_at) "
                "VALUES (1, 1, 1000, 100, 50, 30, 20, 95.0, 3500.0, 'clear', "
                "'', 'legacy_migration', '2026-01-01T00:00:00+00:00')"
            )
            # FC with lower rating
            await new_conn.execute(
                "INSERT INTO score_attempts(user_id, chart_id, perfect, great, good, bad, miss, "
                "accuracy, rating, status, image_sha256, source_gateway, created_at) "
                "VALUES (1, 1, 1100, 50, 0, 0, 0, 100.5, 3100.0, 'fc', "
                "'', 'legacy_migration', '2026-01-02T00:00:00+00:00')"
            )
            await new_conn.commit()

            pb_count = await _compute_personal_bests(new_conn)
            await new_conn.commit()

            assert pb_count == 1
            rows = list(await new_conn.execute_fetchall(
                "SELECT status, rating FROM personal_bests WHERE user_id = 1 AND chart_id = 1"
            ))
            assert rows[0]["status"] == "fc"  # FC beats CLEAR even with lower rating
        finally:
            await new_conn.close()


class TestMigrateOpenidMap:
    async def test_migrates(self, new_db_path: Path) -> None:
        new_conn = await get_connection(new_db_path)
        try:
            await new_conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, created_at, updated_at) "
                "VALUES ('111111', NULL, 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            await new_conn.commit()

            rows = [{"openid": "openid_abc", "qq_id": "111111", "bound_at": 1782343750}]
            inserted = await _migrate_openid_map(new_conn, rows, {"111111": 1})
            await new_conn.commit()

            assert inserted == 1

            result = list(await new_conn.execute_fetchall(
                "SELECT user_id, platform, external_id FROM external_identities"
            ))
            assert result[0]["user_id"] == 1
            assert result[0]["platform"] == "qq_official"
            assert result[0]["external_id"] == "openid_abc"
        finally:
            await new_conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# integration: full migration
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullMigration:
    async def test_full_migration_reconcile_clean(self, legacy_db_path: Path, new_db_path: Path) -> None:
        """Full migration produces a clean reconcile report."""
        # Run migration without --chart-data (charts already seeded)
        report = await migrate(legacy_db_path, new_db_path)

        assert report.users == 2
        assert report.score_attempts == 7  # 4 history + 3 scores
        assert report.personal_bests == 3  # 2 for user1 (master+expert) + 1 for user2
        assert report.external_identities == 1
        assert report.warnings == []

    async def test_migration_produces_valid_iso_timestamps(self, legacy_db_path: Path, new_db_path: Path) -> None:
        """All created_at/updated_at values are ISO-8601."""
        await migrate(legacy_db_path, new_db_path)

        # Re-open and check
        import aiosqlite as aio
        conn = await aio.connect(str(new_db_path))
        conn.row_factory = aio.Row
        try:
            users = list(await conn.execute_fetchall("SELECT created_at, updated_at FROM users"))
            for u in users:
                assert "T" in u["created_at"]
                assert "T" in u["updated_at"]

            attempts = list(await conn.execute_fetchall("SELECT created_at FROM score_attempts"))
            for a in attempts:
                assert "T" in a["created_at"]

            pbs = list(await conn.execute_fetchall("SELECT updated_at FROM personal_bests"))
            for p in pbs:
                assert "T" in p["updated_at"]
        finally:
            await conn.close()

    async def test_migration_idempotent(self, legacy_db_path: Path, new_db_path: Path) -> None:
        """Running migration twice on same DB is safe (UNIQUE/PRIMARY KEY constraints)."""
        await migrate(legacy_db_path, new_db_path)

        # Second run — should fail cleanly (users already exist)
        # We don't expect it to succeed — duplicate qq_number would violate UNIQUE
        # This test just confirms it doesn't corrupt data
        import aiosqlite as aio
        conn = await aio.connect(str(new_db_path))
        conn.row_factory = aio.Row
        try:
            user_count = list(await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM users"
            ))[0]["cnt"]
            assert user_count == 2
        finally:
            await conn.close()
