"""SQLite UserRepository contract tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteUserRepository
from pjsk_core.domain.users import QqNumber, UserId
from pjsk_core.ports.repositories import UserRepository


@pytest.fixture
async def repo(tmp_path: Path) -> AsyncGenerator[SqliteUserRepository, None]:
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteUserRepository(conn)
    finally:
        await conn.close()


class TestSqliteUserRepository:
    async def test_create_and_get_by_id(self, repo: SqliteUserRepository) -> None:
        qq = QqNumber("123456789")
        user = await repo.create(qq, game_id="player1")
        assert user.id == UserId(1)
        assert user.qq_number == qq

        fetched = await repo.get_by_id(user.id)
        assert fetched == user

    async def test_get_by_id_not_found(self, repo: SqliteUserRepository) -> None:
        assert await repo.get_by_id(UserId(999)) is None

    async def test_get_by_qq(self, repo: SqliteUserRepository) -> None:
        qq = QqNumber("987654321")
        await repo.create(qq, game_id="player2")

        fetched = await repo.get_by_qq(qq)
        assert fetched is not None
        assert fetched.qq_number == qq

    async def test_get_by_qq_not_found(self, repo: SqliteUserRepository) -> None:
        assert await repo.get_by_qq(QqNumber("000000")) is None

    async def test_create_duplicate_qq_raises(self, repo: SqliteUserRepository) -> None:
        qq = QqNumber("111222333")
        await repo.create(qq, game_id="p1")
        with pytest.raises(Exception):
            await repo.create(qq, game_id="p2")

    async def test_create_without_game_id(self, repo: SqliteUserRepository) -> None:
        user = await repo.create(QqNumber("55555"), game_id=None)
        assert user.game_id is None

    async def test_roundtrip_timestamps(self, repo: SqliteUserRepository) -> None:
        user = await repo.create(QqNumber("66666"), game_id=None)
        fetched = await repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.created_at is not None
        assert fetched.created_at.tzinfo is not None  # timezone-aware

    async def test_conforms_to_user_repository_protocol(
        self, repo: SqliteUserRepository
    ) -> None:
        """Structural conformance: SqliteUserRepository satisfies UserRepository."""
        _: UserRepository = repo
        # Basic sanity that all protocol methods are callable
        assert callable(repo.get_by_id)
        assert callable(repo.get_by_qq)
        assert callable(repo.create)
