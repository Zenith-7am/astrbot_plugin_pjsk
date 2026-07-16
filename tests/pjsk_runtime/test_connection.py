"""Tests for ConnectionFactory, UnitOfWork, and open_readonly_sqlite."""
import sqlite3
from pathlib import Path

import pytest
from pjsk_runtime.connection import (
    ConnectionFactory,
    UnitOfWork,
    open_readonly_sqlite,
)


class TestConnectionFactory:
    async def test_connect_returns_aiosqlite_connection(self, tmp_path: Path) -> None:
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db)
        conn = await factory.connect()
        try:
            row = await conn.execute_fetchall("SELECT 1 AS n")
            assert row[0]["n"] == 1
        finally:
            await conn.close()

    async def test_readonly_connect_rejects_writes(self, tmp_path: Path) -> None:
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db, readonly=True)
        conn = await factory.connect()
        try:
            # PRAGMA query_only must be ON
            row = await conn.execute_fetchall("PRAGMA query_only")
            assert row[0]["query_only"] == 1

            # INSERT must fail
            with pytest.raises(sqlite3.OperationalError):
                await conn.execute("INSERT INTO users(qq_number, created_at, updated_at) VALUES ('123456', '2026-01-01', '2026-01-01')")
        finally:
            await conn.close()

    async def test_db_path_property(self) -> None:
        factory = ConnectionFactory("/tmp/test.db")
        assert factory.db_path == Path("/tmp/test.db")


class TestUnitOfWork:
    async def test_commit_on_success(self, tmp_path: Path) -> None:
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db)

        async with UnitOfWork(factory) as uow:
            await uow.connection.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, "
                "created_at, updated_at) "
                "VALUES ('11111', NULL, 1, '2026-01-01', '2026-01-01')"
            )
            await uow.connection.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, "
                "created_at, updated_at) "
                "VALUES ('22222', NULL, 1, '2026-01-01', '2026-01-01')"
            )

        # Both rows committed
        conn = await factory.connect()
        try:
            rows = await conn.execute_fetchall(
                "SELECT qq_number FROM users ORDER BY id"
            )
            assert [r["qq_number"] for r in rows] == ["11111", "22222"]
        finally:
            await conn.close()

    async def test_rollback_on_exception(self, tmp_path: Path) -> None:
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db)

        class TestError(Exception):
            pass

        with pytest.raises(TestError):
            async with UnitOfWork(factory) as uow:
                await uow.connection.execute(
                    "INSERT INTO users(qq_number, game_id, append_excluded, "
                    "created_at, updated_at) "
                    "VALUES ('11111', NULL, 1, '2026-01-01', '2026-01-01')"
                )
                raise TestError("simulated failure")

        # Row must NOT exist — rolled back
        conn = await factory.connect()
        try:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM users"
            )
            assert rows[0]["cnt"] == 0
        finally:
            await conn.close()

    async def test_rollback_preserves_previous_data(self, tmp_path: Path) -> None:
        """Verify rollback doesn't affect data committed before the UoW."""
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db)

        # Pre-seed a row outside UoW
        conn = await factory.connect()
        try:
            await conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, "
                "created_at, updated_at) "
                "VALUES ('existing', NULL, 1, '2026-01-01', '2026-01-01')"
            )
            await conn.commit()
        finally:
            await conn.close()

        # UoW that fails
        class TestError(Exception):
            pass

        with pytest.raises(TestError):
            async with UnitOfWork(factory) as uow:
                await uow.connection.execute(
                    "INSERT INTO users(qq_number, game_id, append_excluded, "
                    "created_at, updated_at) "
                    "VALUES ('new_fail', NULL, 1, '2026-01-01', '2026-01-01')"
                )
                raise TestError("simulated failure")

        # Only pre-seeded row exists
        conn = await factory.connect()
        try:
            rows = await conn.execute_fetchall(
                "SELECT qq_number FROM users ORDER BY id"
            )
            assert [r["qq_number"] for r in rows] == ["existing"]
        finally:
            await conn.close()

    async def test_connection_raises_outside_context(self) -> None:
        factory = ConnectionFactory("/tmp/test.db")
        uow = UnitOfWork(factory)
        with pytest.raises(RuntimeError, match="not entered"):
            _ = uow.connection

    async def test_score_and_ocr_in_same_transaction(
        self, tmp_path: Path,
    ) -> None:
        """Simulate score_attempts + ocr_runs in one UoW — all or nothing."""
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db)

        # Pre-seed user and chart
        conn = await factory.connect()
        try:
            await conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, "
                "created_at, updated_at) "
                "VALUES ('12345', NULL, 1, '2026-01-01', '2026-01-01')"
            )
            await conn.execute(
                "INSERT INTO songs(id, title_ja) VALUES (1, 'Test')"
            )
            await conn.execute(
                "INSERT INTO charts(id, song_id, difficulty, official_level, "
                "community_constant, note_count, chart_data_version) "
                "VALUES (1, 1, 'master', 30, '30.5', 1200, 'v1')"
            )
            await conn.commit()
        finally:
            await conn.close()

        class OcrSaveError(Exception):
            pass

        with pytest.raises(OcrSaveError):
            async with UnitOfWork(factory) as uow:
                # Simulate ScoreRepository.record_attempt
                await uow.connection.execute(
                    "INSERT INTO score_attempts "
                    "(user_id, chart_id, perfect, great, good, bad, miss, "
                    "accuracy, rating, status, image_sha256, source_gateway, "
                    "ocr_run_id, created_at) "
                    "VALUES (1, 1, 1000, 100, 0, 0, 0, 100.5, 3100.0, 'fc', "
                    "'abc', 'onebot', NULL, '2026-01-01')"
                )
                # Simulate OcrRunRepository.save — fails
                raise OcrSaveError("OCR save failed")

        # Neither score_attempts nor personal_bests should have rows
        conn = await factory.connect()
        try:
            sa = await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM score_attempts"
            )
            pb = await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM personal_bests"
            )
            assert sa[0]["cnt"] == 0
            assert pb[0]["cnt"] == 0
        finally:
            await conn.close()

    async def test_score_and_pb_both_committed_on_success(
        self, tmp_path: Path,
    ) -> None:
        """Simulate score_attempts + personal_bests in one UoW — both committed."""
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        factory = ConnectionFactory(db)

        # Pre-seed user and chart
        conn = await factory.connect()
        try:
            await conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, "
                "created_at, updated_at) "
                "VALUES ('12345', NULL, 1, '2026-01-01', '2026-01-01')"
            )
            await conn.execute(
                "INSERT INTO songs(id, title_ja) VALUES (1, 'Test')"
            )
            await conn.execute(
                "INSERT INTO charts(id, song_id, difficulty, official_level, "
                "community_constant, note_count, chart_data_version) "
                "VALUES (1, 1, 'master', 30, '30.5', 1200, 'v1')"
            )
            await conn.commit()
        finally:
            await conn.close()

        async with UnitOfWork(factory) as uow:
            # Step 1: Simulate ScoreRepository.record_attempt
            await uow.connection.execute(
                "INSERT INTO score_attempts "
                "(user_id, chart_id, perfect, great, good, bad, miss, "
                "accuracy, rating, status, image_sha256, source_gateway, "
                "ocr_run_id, created_at) "
                "VALUES (1, 1, 1000, 100, 0, 0, 0, 100.5, 3100.0, 'fc', "
                "'abc', 'onebot', NULL, '2026-01-01')"
            )
            # Step 2: Simulate personal_bests UPSERT (same transaction)
            await uow.connection.execute(
                "INSERT INTO personal_bests "
                "(user_id, chart_id, best_attempt_id, accuracy, "
                "rating, status, updated_at) "
                "VALUES (1, 1, 1, 100.5, 3100.0, 'fc', '2026-01-01')"
                " ON CONFLICT(user_id, chart_id) DO UPDATE SET "
                "best_attempt_id = excluded.best_attempt_id, "
                "accuracy = excluded.accuracy, "
                "rating = excluded.rating, "
                "status = excluded.status, "
                "updated_at = excluded.updated_at"
            )
        # UoW committed — both tables must have data

        conn = await factory.connect()
        try:
            sa = await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM score_attempts"
            )
            pb = await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM personal_bests"
            )
            assert sa[0]["cnt"] == 1
            assert pb[0]["cnt"] == 1

            # Verify consistency — personal_bests best_attempt_id points to valid score
            pb_row = await conn.execute_fetchall(
                "SELECT best_attempt_id, rating FROM personal_bests "
                "WHERE user_id = 1 AND chart_id = 1"
            )
            assert pb_row[0]["best_attempt_id"] == 1
            assert pb_row[0]["rating"] == 3100.0

            sa_row = await conn.execute_fetchall(
                "SELECT id, rating FROM score_attempts WHERE id = 1"
            )
            assert sa_row[0]["id"] == 1
            assert sa_row[0]["rating"] == 3100.0
        finally:
            await conn.close()


class TestOpenReadonlySqlite:
    async def test_readonly_enforced(self, tmp_path: Path) -> None:
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)

        # Seed one row with a writable connection
        from adapters.database.connection import get_connection
        w_conn = await get_connection(db)
        try:
            await w_conn.execute(
                "INSERT INTO users(qq_number, game_id, append_excluded, "
                "created_at, updated_at) "
                "VALUES ('11111', NULL, 1, '2026-01-01', '2026-01-01')"
            )
            await w_conn.commit()
        finally:
            await w_conn.close()

        # Read-only connection can read
        conn = await open_readonly_sqlite(db)
        try:
            row = await conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM users"
            )
            assert row[0]["cnt"] == 1
        finally:
            await conn.close()

    async def test_readonly_rejects_insert(self, tmp_path: Path) -> None:
        from adapters.database.migrator import run_migrations
        db = tmp_path / "test.db"
        await run_migrations(db)
        conn = await open_readonly_sqlite(db)
        try:
            with pytest.raises(sqlite3.OperationalError):
                await conn.execute(
                    "INSERT INTO users(qq_number, created_at, updated_at) VALUES ('test123', '2026-01-01', '2026-01-01')"
                )
        finally:
            await conn.close()
