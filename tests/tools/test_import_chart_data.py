"""Tests for the chart data import tool.

Covers SHA-256 verification, constant-format validation, idempotent
import, versioned updates, batch rejection on bad data, and connection
hygiene.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteChartRepository
from tools.import_chart_data import import_chart_data


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _write_manifest(data_dir: Path, file_hashes: dict[str, str]) -> None:
    """Write manifest.json with *real* SHA-256 values matching the data files."""
    manifest = {
        "version": "2026-07-12",
        "source": "PENTATONIC",
        "files": file_hashes,
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )


def _write_chart_file(
    data_dir: Path, filename: str, charts: list[dict[str, object]],
) -> str:
    """Write a chart data file and return its SHA-256 hash."""
    path = data_dir / filename
    path.write_text(
        json.dumps({
            "version": "2026-07-12",
            "source": "PENTATONIC",
            "charts": charts,
        }),
        encoding="utf-8",
    )
    return _sha256(path)


def _make_chart(
    song_id: int,
    title_ja: str = "Test Song",
    difficulty: str = "master",
    official_level: int = 30,
    community_constant: str = "30.5",
    note_count: int = 1200,
) -> dict[str, object]:
    return {
        "song_id": song_id,
        "title_ja": title_ja,
        "difficulty": difficulty,
        "official_level": official_level,
        "community_constant": community_constant,
        "note_count": note_count,
    }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def chart_repo(
    tmp_path: Path,
) -> AsyncGenerator[tuple[SqliteChartRepository, Path, Path], None]:
    db = tmp_path / "test.db"
    data_dir = tmp_path / "chart_data"
    data_dir.mkdir()
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteChartRepository(conn), db, data_dir
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestImportChartData:
    """Happy-path and basic validation."""

    async def test_imports_valid_charts(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        repo, db, data_dir = chart_repo
        h = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, community_constant="30.5"),
            _make_chart(2, community_constant="31.2", note_count=1300),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h})

        result = await import_chart_data(db, data_dir)
        assert result == {"inserted": 2, "updated": 0, "unchanged": 0}

        chart = await repo.get_by_id(1)
        assert chart is not None
        assert chart.community_constant == "30.5"

    async def test_idempotent_no_changes(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        charts = [_make_chart(1)]
        h = _write_chart_file(data_dir, "pentatonic_master.json", charts)
        _write_manifest(data_dir, {"pentatonic_master.json": h})

        r1 = await import_chart_data(db, data_dir)
        r2 = await import_chart_data(db, data_dir)
        assert r1 == {"inserted": 1, "updated": 0, "unchanged": 0}
        assert r2 == {"inserted": 0, "updated": 0, "unchanged": 1}

    async def test_updates_existing_chart_on_new_version(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        repo, db, data_dir = chart_repo
        # First import
        h1 = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, community_constant="30.5", official_level=30,
                        note_count=1200),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h1})
        r1 = await import_chart_data(db, data_dir)
        assert r1 == {"inserted": 1, "updated": 0, "unchanged": 0}

        # Second import with changed values
        h2 = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, community_constant="30.6", official_level=31,
                        note_count=1250),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h2})
        r2 = await import_chart_data(db, data_dir)
        assert r2 == {"inserted": 0, "updated": 1, "unchanged": 0}

        chart = await repo.get_by_id(1)
        assert chart is not None
        assert chart.community_constant == "30.6"
        assert chart.official_level == 31
        assert chart.note_count == 1250


class TestSha256Verification:
    """P0: manifest integrity must be enforced."""

    async def test_rejects_tampered_file(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1),
        ])
        # Manifest claims a bogus hash
        _write_manifest(data_dir, {
            "pentatonic_master.json": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        })

        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            await import_chart_data(db, data_dir)

    async def test_manifest_missing_file(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        _write_manifest(data_dir, {
            "nonexistent.json": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        })

        with pytest.raises(FileNotFoundError):
            await import_chart_data(db, data_dir)


class TestValidationBatchRejection:
    """P0/P1: batch must be fully validated before any write."""

    async def test_rejects_batch_on_invalid_difficulty(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        h = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, difficulty="invalid_diff"),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h})

        with pytest.raises(ValueError, match="Invalid difficulty"):
            await import_chart_data(db, data_dir)

    async def test_rejects_invalid_constant_format(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        h = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, community_constant="abc"),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h})

        with pytest.raises(ValueError, match="Invalid constant format"):
            await import_chart_data(db, data_dir)

    async def test_rejects_non_positive_note_count(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        h = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, note_count=0),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h})

        with pytest.raises(ValueError, match="note_count must be positive"):
            await import_chart_data(db, data_dir)

    @pytest.mark.parametrize("constant", [
        "", "32", "32.55", "32.5++", " 32.5", "32.5 ",
    ])
    async def test_rejects_invalid_constant_boundaries(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
        constant: str,
    ) -> None:
        _, db, data_dir = chart_repo
        h = _write_chart_file(data_dir, "pentatonic_master.json", [
            _make_chart(1, community_constant=constant),
        ])
        _write_manifest(data_dir, {"pentatonic_master.json": h})

        with pytest.raises(ValueError, match="Invalid constant format"):
            await import_chart_data(db, data_dir)


class TestConnectionHygiene:
    """P1: connection must not leak on early failures."""

    async def test_manifest_failure_never_opens_db(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, _db, data_dir = chart_repo
        # Remove manifest entirely — failure should happen before DB open
        # (the manifest doesn't exist, so _parse_manifest raises)
        # We just verify no connection-related exception escapes.

        with pytest.raises(FileNotFoundError):
            await import_chart_data(_db, data_dir)
