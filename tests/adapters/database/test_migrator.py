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

    async def test_rollback_on_failed_migration(self, tmp_path: Path) -> None:
        """Mid-migration failure must roll back completely — no partial DDL,
        no schema_version increment."""
        import shutil
        from pathlib import Path as P

        db = tmp_path / "test.db"
        real_dir = P(__file__).parent.parent.parent.parent / "adapters" / "database" / "migrations"
        test_dir = tmp_path / "migrations"
        test_dir.mkdir()
        for f in real_dir.glob("*.sql"):
            shutil.copy(f, test_dir / f.name)
        # Migration 002: first statement valid, second invalid
        (test_dir / "002_bad.sql").write_text(
            "CREATE TABLE should_rollback (x INTEGER);\n"
            "THIS IS NOT VALID SQL;",
            encoding="utf-8",
        )

        with pytest.raises(Exception):
            await run_migrations(db, migrations_dir=test_dir)

        conn = sqlite3.connect(str(db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "users" in tables            # 001 applied
        assert "should_rollback" not in tables  # 002 rolled back
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert row[0] == 1  # only 001 recorded
        conn.close()
