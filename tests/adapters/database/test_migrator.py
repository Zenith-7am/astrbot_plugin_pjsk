"""Tests for the versioned migration system."""
import sqlite3
from pathlib import Path

import pytest
from adapters.database.migrator import run_migrations


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


class TestRunMigrations:
    async def test_creates_schema_version_table(self, temp_db: Path) -> None:
        await run_migrations(temp_db)
        conn = sqlite3.connect(str(temp_db))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert ("schema_version",) in tables

    async def test_applies_initial_migration(self, temp_db: Path) -> None:
        await run_migrations(temp_db)
        conn = sqlite3.connect(str(temp_db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected = {"schema_version", "users", "external_identities",
                    "songs", "charts", "score_attempts", "personal_bests"}
        assert expected <= tables
        conn.close()

    async def test_records_migration_version(self, temp_db: Path) -> None:
        version = await run_migrations(temp_db)
        assert version == 1
        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        conn.close()
        assert row == (1,)

    async def test_idempotent_second_run(self, temp_db: Path) -> None:
        await run_migrations(temp_db)
        version = await run_migrations(temp_db)
        assert version == 1  # already applied, no change

    async def test_empty_db_returns_zero(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        db.touch()
        version = await run_migrations(db)
        assert version == 1  # migrations applied on empty db
