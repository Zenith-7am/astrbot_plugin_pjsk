"""Tests for SqliteOcrRunRepository."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.ocr_run_repository import SqliteOcrRunRepository
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


async def _seed_user(db: Path) -> None:
    """Insert a user with id=1 so FK constraints pass."""
    conn = await get_connection(db)
    try:
        await conn.execute(
            "INSERT INTO users(id, qq_number, game_id, created_at, updated_at) "
            "VALUES (1, '123456789', 'player1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        await conn.commit()
    finally:
        await conn.close()


async def _repo_with_user(tmp_path: Path) -> SqliteOcrRunRepository:
    """Create a fresh database, run migrations, seed a user, return repo."""
    db = tmp_path / "test.db"
    await run_migrations(db)
    await _seed_user(db)
    return SqliteOcrRunRepository(db)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteOcrRunRepository:
    return await _repo_with_user(tmp_path)


class TestSqliteOcrRunRepository:
    async def test_save_and_retrieve(self, repo: SqliteOcrRunRepository) -> None:
        obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="a" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(obs,), created_at=datetime.now(timezone.utc),
        )
        saved = await repo.save(record)
        assert saved.id is not None

        fetched = await repo.get_by_id(saved.id)
        assert fetched is not None
        assert fetched.final_state == "consensus"
        assert len(fetched.observations) == 1
        assert fetched.observations[0].result_status == "success"
        assert fetched.observations[0].song_title == "Test"

    async def test_save_multiple_observations(self, repo: SqliteOcrRunRepository) -> None:
        obs_g = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Song A", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        obs_z = OcrEngineRecord(
            engine_id="z", provider="zhipu", result_status="failed",
            elapsed_ms=5000, song_title=None, difficulty=None,
            displayed_level=None, judgements=None,
            matched_chart_id=None, validation_status=None,
            error_type="timeout",
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="b" * 64, source_gateway="astrbot",
            final_state="disagreement", selected_engine=None,
            observations=(obs_g, obs_z), created_at=datetime.now(timezone.utc),
        )
        saved = await repo.save(record)
        assert saved.id is not None
        fetched = await repo.get_by_id(saved.id)
        assert fetched is not None
        assert len(fetched.observations) == 2

    async def test_get_by_id_not_found(self, repo: SqliteOcrRunRepository) -> None:
        assert await repo.get_by_id(999) is None

    async def test_rollback_on_error(self, tmp_path: Path) -> None:
        """If observations INSERT fails, ocr_runs row must be rolled back."""
        db = tmp_path / "test.db"
        await run_migrations(db)
        await _seed_user(db)
        repo = SqliteOcrRunRepository(db)
        # An observation with invalid difficulty should fail the CHECK constraint
        bad_obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test", difficulty="INVALID",  # type: ignore[arg-type]
            displayed_level=30,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="c" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(bad_obs,), created_at=datetime.now(timezone.utc),
        )
        try:
            await repo.save(record)
        except Exception:
            pass
        # The ocr_runs row should not exist
        assert await repo.get_by_id(1) is None

    async def test_uses_independent_connection(self, tmp_path: Path) -> None:
        """Each save() call creates its own connection -- no shared state."""
        db = tmp_path / "test.db"
        await run_migrations(db)
        await _seed_user(db)
        repo = SqliteOcrRunRepository(db)
        obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="T", difficulty=Difficulty.EASY,
            displayed_level=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="d" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(obs,), created_at=datetime.now(timezone.utc),
        )
        # Two concurrent saves should both succeed (independent connections)
        import asyncio
        results = await asyncio.gather(
            repo.save(record),
            repo.save(record),
        )
        assert results[0].id is not None
        assert results[1].id is not None
        assert results[0].id != results[1].id
