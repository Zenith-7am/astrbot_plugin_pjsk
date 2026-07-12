"""Tests for the chart data import tool."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteChartRepository
from tools.import_chart_data import import_chart_data


def _write_chart_data(data_dir: Path, charts: list[dict[str, object]]) -> None:
    data_file = data_dir / "pentatonic_master.json"
    data_file.write_text(
        json.dumps({"version": "2026-07-12", "source": "PENTATONIC", "charts": charts}),
        encoding="utf-8",
    )
    manifest = data_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"version": "2026-07-12", "files": {"pentatonic_master.json": "sha256:test"}}),
        encoding="utf-8",
    )


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


class TestImportChartData:
    async def test_imports_valid_charts(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        repo, db, data_dir = chart_repo
        _write_chart_data(data_dir, [
            {
                "song_id": 1, "title_ja": "Test Song",
                "difficulty": "master", "official_level": 30,
                "community_constant": "30.5", "note_count": 1200,
            },
            {
                "song_id": 2, "title_ja": "Song 2",
                "difficulty": "master", "official_level": 31,
                "community_constant": "31.2", "note_count": 1300,
            },
        ])
        count = await import_chart_data(db, data_dir)
        assert count == 2

        chart = await repo.get_by_id(1)
        assert chart is not None
        assert chart.community_constant == "30.5"

    async def test_rejects_invalid_constant_format(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        _write_chart_data(data_dir, [
            {
                "song_id": 1, "title_ja": "Bad",
                "difficulty": "master", "official_level": 30,
                "community_constant": "abc", "note_count": 1000,
            },
        ])
        with pytest.raises(ValueError):
            await import_chart_data(db, data_dir)

    async def test_skips_invalid_difficulty(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        _write_chart_data(data_dir, [
            {
                "song_id": 1, "title_ja": "Test",
                "difficulty": "invalid_diff", "official_level": 30,
                "community_constant": "30.0", "note_count": 1000,
            },
        ])
        count = await import_chart_data(db, data_dir)
        assert count == 0

    async def test_idempotent_import(
        self,
        chart_repo: tuple[SqliteChartRepository, Path, Path],
    ) -> None:
        _, db, data_dir = chart_repo
        charts = [{
            "song_id": 1, "title_ja": "Test",
            "difficulty": "master", "official_level": 30,
            "community_constant": "30.5", "note_count": 1200,
        }]
        _write_chart_data(data_dir, charts)
        c1 = await import_chart_data(db, data_dir)
        c2 = await import_chart_data(db, data_dir)
        assert c1 == 1
        assert c2 == 0  # already imported, skip
