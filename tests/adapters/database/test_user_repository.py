"""SQLite UserRepository contract tests."""

import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteUserRepository
from pjsk_core.domain.users import QqNumber, UserId
from pjsk_core.ports.repositories import (
    AlreadyBoundError,
    DuplicateGameIdError,
    UserRepository,
)


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
        with pytest.raises(sqlite3.IntegrityError):
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
        assert callable(repo.bind_game_id)


class TestBindGameId:
    """Tests for atomic game_id binding (Commit 2 R4)."""

    @pytest.fixture
    async def repo(  # type: ignore[no-untyped-def]
        self, tmp_path: Path,
    ):
        db = tmp_path / "test.db"
        await run_migrations(db)
        conn = await get_connection(db)
        try:
            yield SqliteUserRepository(conn)
        finally:
            await conn.close()

    async def test_bind_new_game_id_to_user(self, repo: SqliteUserRepository) -> None:
        """User with game_id=None can be bound."""
        user = await repo.create(QqNumber("111111"), game_id=None)
        assert user.game_id is None
        updated = await repo.bind_game_id(user.id, "9876543210987654")
        assert updated.game_id == "9876543210987654"
        # Verify persistence
        fetched = await repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.game_id == "9876543210987654"

    async def test_bind_same_game_id_idempotent(self, repo: SqliteUserRepository) -> None:
        """Binding the same game_id again should succeed (idempotent)."""
        user = await repo.create(QqNumber("222222"), game_id=None)
        updated1 = await repo.bind_game_id(user.id, "1111111111111111")
        assert updated1.game_id == "1111111111111111"
        updated2 = await repo.bind_game_id(user.id, "1111111111111111")
        assert updated2.game_id == "1111111111111111"

    async def test_duplicate_game_id_raises(self, repo: SqliteUserRepository) -> None:
        """Two different QQ accounts cannot share the same game_id."""
        await repo.create(QqNumber("333333"), game_id="1234567890123456")
        user2 = await repo.create(QqNumber("444444"), game_id=None)
        with pytest.raises(DuplicateGameIdError):
            await repo.bind_game_id(user2.id, "1234567890123456")

    async def test_update_null_game_id(self, repo: SqliteUserRepository) -> None:
        """Auto-registered user (game_id=None) can be bound."""
        user = await repo.create(QqNumber("555555"), game_id=None)
        updated = await repo.bind_game_id(user.id, "5555555555555555")
        assert updated.game_id == "5555555555555555"

    async def test_rebind_different_game_id_raises(self, repo: SqliteUserRepository) -> None:
        """Changing a bound game_id should raise AlreadyBoundError."""
        user = await repo.create(QqNumber("666666"), game_id="6666666666666666")
        with pytest.raises(AlreadyBoundError):
            await repo.bind_game_id(user.id, "7777777777777777")

    async def test_bind_idempotent_same_value(self, repo: SqliteUserRepository) -> None:
        """Calling bind_game_id with the same game_id is idempotent."""
        user = await repo.create(QqNumber("777777"), game_id=None)
        updated1 = await repo.bind_game_id(user.id, "8888888888888888")
        assert updated1.game_id == "8888888888888888"
        # Same value again — should succeed
        updated2 = await repo.bind_game_id(user.id, "8888888888888888")
        assert updated2.game_id == "8888888888888888"
