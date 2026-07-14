"""SQLite SongRepository contract tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.song_repository import SqliteSongRepository
from pjsk_core.domain.song import Song
from pjsk_core.ports.repositories import SongRepository


@pytest.fixture
async def repo(tmp_path: Path) -> AsyncGenerator[SqliteSongRepository, None]:
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteSongRepository(conn)
    finally:
        await conn.close()


class TestSqliteSongRepository:
    """CRUD operations for the songs table."""

    async def test_get_by_id(self, repo: SqliteSongRepository) -> None:
        await repo._conn.execute(
            "INSERT INTO songs(id, title_ja, title_cn, title_en, aliases) "
            "VALUES (1, 'テスト曲', '测试曲', 'Test Song', '[]')"
        )
        await repo._conn.commit()
        song = await repo.get_by_id(1)
        assert song is not None
        assert isinstance(song, Song)
        assert song.id == 1
        assert song.title_ja == 'テスト曲'
        assert song.title_cn == '测试曲'
        assert song.title_en == 'Test Song'
        assert song.aliases == '[]'

    async def test_get_by_id_not_found(self, repo: SqliteSongRepository) -> None:
        assert await repo.get_by_id(999) is None

    async def test_get_all(self, repo: SqliteSongRepository) -> None:
        songs_data = [
            (2, '曲B', '歌B', 'Song B', '["b"]'),
            (1, '曲A', '歌A', 'Song A', '["a"]'),
            (3, '曲C', '歌C', 'Song C', '[]'),
        ]
        for row in songs_data:
            await repo._conn.execute(
                "INSERT INTO songs(id, title_ja, title_cn, title_en, aliases) "
                "VALUES (?, ?, ?, ?, ?)",
                row,
            )
        await repo._conn.commit()

        result = await repo.get_all()
        assert len(result) == 3
        # Should be sorted by id
        assert [s.id for s in result] == [1, 2, 3]
        for s in result:
            assert isinstance(s, Song)

    async def test_conforms_to_song_repository_protocol(
        self, repo: SqliteSongRepository
    ) -> None:
        """Structural conformance: SqliteSongRepository satisfies SongRepository."""
        _: SongRepository = repo
        assert callable(repo.get_by_id)
        assert callable(repo.get_all)
