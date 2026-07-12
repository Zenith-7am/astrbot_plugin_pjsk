"""SQLite ChartRepository contract tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from aiosqlite import Connection
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteChartRepository
from pjsk_core.domain.charts import Difficulty
from pjsk_core.ports.repositories import ChartRepository


@pytest.fixture
async def repo(tmp_path: Path) -> AsyncGenerator[SqliteChartRepository, None]:
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteChartRepository(conn)
    finally:
        await conn.close()


async def _seed_song_and_chart(
    conn: Connection,
    song_id: int = 1,
    difficulty: str = "master",
    official_level: int = 30,
    constant: str = "30.5",
    note_count: int = 1200,
) -> None:
    await conn.execute(
        "INSERT INTO songs(id, title_ja) VALUES (?, ?)",
        (song_id, "Test Song"),
    )
    await conn.execute(
        "INSERT INTO charts(song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (song_id, difficulty, official_level, constant, note_count, "2026-07-12"),
    )
    await conn.commit()


class TestSqliteChartRepository:
    async def test_get_by_id(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn)
        chart = await repo.get_by_id(1)
        assert chart is not None
        assert chart.song_id == 1
        assert chart.difficulty == Difficulty.MASTER

    async def test_get_by_id_not_found(self, repo: SqliteChartRepository) -> None:
        assert await repo.get_by_id(999) is None

    async def test_find_by_song_and_difficulty(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=42)
        chart = await repo.find_by_song_and_difficulty("Test Song", Difficulty.MASTER)
        assert chart is not None
        assert chart.song_id == 42

    async def test_list_by_difficulty_level(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=1, difficulty="master", official_level=30)
        await _seed_song_and_chart(repo._conn, song_id=2, difficulty="master", official_level=31)
        await _seed_song_and_chart(repo._conn, song_id=3, difficulty="expert", official_level=30)
        songs = [
            (4, "Song4"), (5, "Song5"),
        ]
        for sid, title in songs:
            await repo._conn.execute(
                "INSERT INTO songs(id, title_ja) VALUES (?, ?)", (sid, title)
            )
        for sid, level, const in [(4, 30, "30.0"), (5, 31, "31.0")]:
            await repo._conn.execute(
                "INSERT INTO charts(song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
                "VALUES (?, 'master', ?, ?, 1000, '2026-07-12')",
                (sid, level, const),
            )
        await repo._conn.commit()

        level30 = await repo.list_by_difficulty_level(Difficulty.MASTER, 30)
        assert len(level30) == 2  # song_ids 1, 4

        level31 = await repo.list_by_difficulty_level(Difficulty.MASTER, 31)
        assert len(level31) == 2  # song_ids 2, 5

        level32 = await repo.list_by_difficulty_level(Difficulty.MASTER, 32)
        assert len(level32) == 0

    async def test_conforms_to_chart_repository_protocol(
        self, repo: SqliteChartRepository
    ) -> None:
        """Structural conformance: SqliteChartRepository satisfies ChartRepository."""
        _: ChartRepository = repo
        assert callable(repo.get_by_id)
        assert callable(repo.find_by_song_and_difficulty)
        assert callable(repo.list_by_difficulty_level)
