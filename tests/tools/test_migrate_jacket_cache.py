"""Tests for jacket cache migration tool — dry-run + apply modes."""

import json
from pathlib import Path

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────

# Minimal image payloads (all ≥100 bytes)
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_JPG = b"\xff\xd8\xff" + b"\x00" * 100
_WEBP = b"RIFF\x5a\x00\x00\x00WEBPVP8 \x1a\x00\x00\x00" + b"\x00" * 90


@pytest.fixture
def old_cache_dir(tmp_path: Path) -> Path:
    """Create a realistic old cache directory matching VPS reality:
    734 PNG, 4 JPG, 7 WebP — scaled down for test."""
    d = tmp_path / "old_jackets"
    d.mkdir()

    # Very old format: jacket_s_042.png
    (d / "jacket_s_001.png").write_bytes(_PNG)
    (d / "jacket_s_042.png").write_bytes(_PNG)

    # Zero-padded JPG
    (d / "001.jpg").write_bytes(_JPG)
    (d / "042.jpg").write_bytes(_JPG)

    # Plain JPG
    (d / "100.jpg").write_bytes(_JPG)
    (d / "200.jpg").write_bytes(_JPG)

    # Zero-padded PNG
    (d / "010.png").write_bytes(_PNG)

    # WebP (the 7 files missed by the old patterns)
    (d / "300.webp").write_bytes(_WEBP)
    (d / "301.webp").write_bytes(_WEBP)

    # Unrelated files — should be skipped
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

    def test_dry_run_reports_file_count(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Dry-run prints scan report, copies nothing."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        assert result.total_files > 0
        assert "png" in result.format_counts
        assert "jpg" in result.format_counts
        assert "webp" in result.format_counts
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

    def test_dry_run_includes_webp(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Old VPS has 7 .webp files — they must be in the manifest."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        assert result.format_counts.get("webp", 0) >= 2
        webp_names = {e["name"] for e in result.manifest if e["format"] == "webp"}
        assert "300.webp" in webp_names
        assert "301.webp" in webp_names

    def test_dry_run_reports_all_formats(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Format counts include png, jpg, and webp."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=False,
        )

        assert result.format_counts.get("png", 0) >= 1
        assert result.format_counts.get("jpg", 0) >= 1
        assert result.format_counts.get("webp", 0) >= 1


class TestMigrateApply:
    """--apply mode copies files and writes manifest."""

    def test_apply_copies_files(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """--apply copies matching files to new dir (never overwrites old dir)."""
        from tools.migrate_jacket_cache import migrate

        result = migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=True,
        )

        assert result.total_files > 0
        assert result.copied == result.total_files  # all are new
        assert result.skipped_identical == 0
        assert result.skipped_conflict == 0
        copied = [p for p in new_cache_dir.iterdir() if p.name != "manifest.json"]
        assert len(copied) == result.total_files

    def test_apply_writes_manifest(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """--apply writes manifest.json with status field per entry."""
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
        for entry in manifest:
            assert "status" in entry, f"manifest entry missing status: {entry['name']}"
            assert entry["status"] in ("copied", "skipped_identical", "skipped_conflict")

    def test_apply_does_not_touch_old_dir(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Old dir files are never modified or deleted."""
        from tools.migrate_jacket_cache import migrate

        before = sorted(p.name for p in old_cache_dir.iterdir())

        migrate(
            old_dir=str(old_cache_dir),
            new_dir=str(new_cache_dir),
            apply=True,
        )

        after = sorted(p.name for p in old_cache_dir.iterdir())
        assert before == after

    def test_apply_dedup_same_song_id(self, tmp_path: Path) -> None:
        """Same song_id in .png and .jpg → both copied (audit trail)."""
        old = tmp_path / "old_dup"
        old.mkdir()
        new = tmp_path / "new_dup"
        new.mkdir()

        (old / "jacket_s_042.png").write_bytes(_PNG)
        (old / "042.jpg").write_bytes(_JPG)

        from tools.migrate_jacket_cache import migrate

        result = migrate(str(old), str(new), apply=True)
        assert result.total_files == 2
        copied = [p for p in new.iterdir() if p.name != "manifest.json"]
        assert len(copied) == 2


# ── Idempotent re-run + conflict protection ─────────────────────────────


class TestApplyNoOverwrite:
    """--apply never overwrites existing target files."""

    def test_rerun_all_skipped_identical(self, old_cache_dir: Path, new_cache_dir: Path) -> None:
        """Second run with same files → all skipped_identical, zero copied."""
        from tools.migrate_jacket_cache import migrate

        # First run
        r1 = migrate(str(old_cache_dir), str(new_cache_dir), apply=True)
        assert r1.copied == r1.total_files

        # Snapshot files after first run
        first_run_files = {
            p.name: p.read_bytes()
            for p in new_cache_dir.iterdir()
            if p.name != "manifest.json"
        }

        # Second run — idempotent
        r2 = migrate(str(old_cache_dir), str(new_cache_dir), apply=True)
        assert r2.copied == 0
        assert r2.skipped_identical == r2.total_files
        assert r2.skipped_conflict == 0

        # Files unchanged after second run
        for p in new_cache_dir.iterdir():
            if p.name == "manifest.json":
                continue
            assert p.read_bytes() == first_run_files[p.name]

    def test_target_has_different_content_skips(self, tmp_path: Path) -> None:
        """Target exists with DIFFERENT content → skipped_conflict, not overwritten."""
        old = tmp_path / "old_src"
        old.mkdir()
        new = tmp_path / "new_dst"
        new.mkdir()

        # Source file
        (old / "042.jpg").write_bytes(_JPG)

        # Pre-existing target file with DIFFERENT content
        different_content = b"\xff\xd8\xff" + b"\x99" * 100
        (new / "042.jpg").write_bytes(different_content)

        from tools.migrate_jacket_cache import migrate

        result = migrate(str(old), str(new), apply=True)
        assert result.total_files == 1
        assert result.copied == 0
        assert result.skipped_identical == 0
        assert result.skipped_conflict == 1

        # Target content NOT overwritten
        assert (new / "042.jpg").read_bytes() == different_content

    def test_target_has_same_content_is_idempotent(self, tmp_path: Path) -> None:
        """Target exists with SAME content → skipped_identical."""
        old = tmp_path / "old_src"
        old.mkdir()
        new = tmp_path / "new_dst"
        new.mkdir()

        # Source file
        (old / "042.jpg").write_bytes(_JPG)

        # Pre-existing target with IDENTICAL content
        (new / "042.jpg").write_bytes(_JPG)

        from tools.migrate_jacket_cache import migrate

        result = migrate(str(old), str(new), apply=True)
        assert result.total_files == 1
        assert result.copied == 0
        assert result.skipped_identical == 1
        assert result.skipped_conflict == 0

    def test_mixed_copy_skip_conflict(self, tmp_path: Path) -> None:
        """Mixed: 2 new, 1 identical, 1 conflict → correct counters."""
        old = tmp_path / "old_mix"
        old.mkdir()
        new = tmp_path / "new_mix"
        new.mkdir()

        (old / "001.jpg").write_bytes(_JPG)       # new
        (old / "002.jpg").write_bytes(_JPG)       # new
        (old / "042.jpg").write_bytes(_JPG)       # identical (pre-seeded below)
        (old / "099.jpg").write_bytes(_JPG)       # conflict (pre-seeded below)

        # Pre-seed: 042.jpg identical, 099.jpg different
        (new / "042.jpg").write_bytes(_JPG)
        (new / "099.jpg").write_bytes(b"\xff\xd8\xff" + b"\xee" * 100)

        from tools.migrate_jacket_cache import migrate

        result = migrate(str(old), str(new), apply=True)
        assert result.total_files == 4
        assert result.copied == 2
        assert result.skipped_identical == 1
        assert result.skipped_conflict == 1

    def test_webp_in_apply_flow(self, tmp_path: Path) -> None:
        """WebP files are copied (not skipped as unrecognized)."""
        old = tmp_path / "old_w"
        old.mkdir()
        new = tmp_path / "new_w"
        new.mkdir()

        (old / "300.webp").write_bytes(_WEBP)
        (old / "301.webp").write_bytes(_WEBP)

        from tools.migrate_jacket_cache import migrate

        result = migrate(str(old), str(new), apply=True)
        assert result.total_files == 2
        assert result.copied == 2
        assert result.format_counts.get("webp", 0) == 2

        copied = [p for p in new.iterdir() if p.name != "manifest.json"]
        assert len(copied) == 2
