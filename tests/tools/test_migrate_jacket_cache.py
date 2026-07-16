"""Tests for jacket cache migration tool — dry-run + apply modes."""

import json
from pathlib import Path

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


@pytest.fixture
def old_cache_dir(tmp_path: Path) -> Path:
    """Create a realistic old cache directory with mixed formats."""
    d = tmp_path / "old_jackets"
    d.mkdir()

    # Very old format: jacket_s_042.png
    (d / "jacket_s_001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    (d / "jacket_s_042.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # Zero-padded JPG
    (d / "001.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    (d / "042.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    # Plain JPG
    (d / "100.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    (d / "200.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    # Plain PNG (zero-padded)
    (d / "010.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # Unrelated file — should be skipped
    (d / "readme.txt").write_text("not a jacket")
    (d / "manifest.json").write_text("{}")

    return d


@pytest.fixture
def new_cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "new_jackets"
    d.mkdir()
    return d


# ── Tests ────────────────────────────────────────────────────────────────


class TestMigrateDryRun:
    """Default dry-run mode reports without copying."""

    def test_dry_run_reports_file_count(self, old_cache_dir: Path, new_cache_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Dry-run prints scan report, copies nothing."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        # Should report files found
        assert result.total_files > 0
        # Should have format breakdown
        assert "png" in result.format_counts or ".png" in str(result.format_counts)
        # Nothing copied to new dir
        copied = list(new_cache_dir.iterdir())
        assert len(copied) == 0

    def test_dry_run_returns_manifest(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Dry-run returns a SHA-256 manifest of scanned files."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        assert result.manifest is not None
        assert len(result.manifest) == result.total_files
        for entry in result.manifest:
            assert "name" in entry
            assert "sha256" in entry
            assert len(entry["sha256"]) == 64

    def test_dry_run_skips_unrecognized_files(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Unrecognized filenames (readme.txt, manifest.json) are excluded."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        names = {e["name"] for e in result.manifest}
        assert "readme.txt" not in names
        assert "manifest.json" not in names

    def test_dry_run_reports_all_formats(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Format counts include png and jpg (old cache has no webp)."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        # Our fixture has 3 .png files and 4 .jpg files
        assert result.format_counts.get("png", 0) >= 1
        assert result.format_counts.get("jpg", 0) >= 1


class TestMigrateApply:
    """--apply mode copies files and writes manifest."""

    def test_apply_copies_files(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """--apply copies matching files to new dir."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=True,
        )

        assert result.total_files > 0
        # Copied files = all items except manifest.json
        copied = [p for p in new_cache_dir.iterdir() if p.name != "manifest.json"]
        assert len(copied) == result.total_files

    def test_apply_writes_manifest(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """--apply writes manifest.json to new dir."""
        from tools.migrate_jacket_cache import migrate

        migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=True,
        )

        manifest_path = new_cache_dir / "manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert isinstance(manifest, list)

        # Verify at least one copied file exists at its new path
        first = manifest[0]
        copied_file = new_cache_dir / first["name"]
        assert copied_file.exists()

    def test_apply_does_not_touch_old_dir(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Old dir files are never modified or deleted."""
        from tools.migrate_jacket_cache import migrate

        # Snapshot old dir before migration
        before = sorted(p.name for p in old_cache_dir.iterdir())

        migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=True,
        )

        after = sorted(p.name for p in old_cache_dir.iterdir())
        assert before == after

    def test_apply_dedup_same_song_id(self, tmp_path: Path) -> None:
        """When the same song_id exists in both .png and .jpg, both are
        copied (format distribution is preserved for audit trail)."""
        old = tmp_path / "old_dup"
        old.mkdir()
        new = tmp_path / "new_dup"
        new.mkdir()

        (old / "jacket_s_042.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        (old / "042.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        from tools.migrate_jacket_cache import migrate

        result = migrate(str(old), str(new), apply=True)
        assert result.total_files == 2
        copied = [p for p in new.iterdir() if p.name != "manifest.json"]
        assert len(copied) == 2  # 2 jacket files (no manifest counted)
