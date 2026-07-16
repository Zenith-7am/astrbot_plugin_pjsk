#!/usr/bin/env python3
"""Migrate legacy jacket cache files to the new shared cache layout.

Reads the old cache directory (e.g. ``/tmp/pjsk_jackets``), matches
files against known legacy naming conventions, and copies them into
the new ``PJSK_JACKET_CACHE_DIR``.

Usage::

    # Dry-run (report only, no copy)
    python tools/migrate_jacket_cache.py \\
        --old-dir /tmp/pjsk_jackets \\
        --new-dir /opt/pjsk-astrbot/shared/cache/jackets

    # Apply (copy files + write manifest.json)
    python tools/migrate_jacket_cache.py \\
        --old-dir /tmp/pjsk_jackets \\
        --new-dir /opt/pjsk-astrbot/shared/cache/jackets \\
        --apply

Legacy patterns recognised:
  - ``jacket_s_{song_id:03d}.png``  (very old)
  - ``{song_id:03d}.png``
  - ``{song_id:03d}.jpg``
  - ``{song_id}.jpg``
  - ``{song_id}.webp``              (new WebP from CDN, already in old cache)

Apply behaviour (no-overwrite guarantee):
  - Target does not exist → copy, status "copied".
  - Target exists with identical SHA-256 → skip, "skipped_identical".
  - Target exists with different SHA-256 → skip, "skipped_conflict".
  The old directory is **never modified or deleted**.
  A ``manifest.json`` with status per file is written to the new
  directory on ``--apply``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MigrationResult:
    """Outcome of a migration run."""

    old_dir: str
    new_dir: str
    applied: bool
    total_files: int = 0
    total_bytes: int = 0
    format_counts: dict[str, int] = field(default_factory=dict)
    manifest: list[dict[str, object]] = field(default_factory=list)
    copied: int = 0
    skipped_identical: int = 0
    skipped_conflict: int = 0


# ── Pattern matching ─────────────────────────────────────────────────────

# (regex, format_label).  Order is priority — first match wins.
_LEGACY_PATTERNS: list[tuple[str, str]] = [
    (r"^jacket_s_(\d{3})\.png$", "png"),
    (r"^(\d{3})\.png$",           "png"),
    (r"^(\d{3})\.jpg$",           "jpg"),
    (r"^(\d+)\.jpg$",             "jpg"),
    (r"^(\d+)\.webp$",            "webp"),
]

# Files matching these names are silently excluded (not jackets).
_EXCLUDE_NAMES = frozenset({"manifest.json", "readme.txt", "README.txt"})


def _sha256_hex(path: str) -> str:
    """Return the SHA-256 hex digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _match_legacy(filename: str) -> tuple[int, str] | None:
    """Return (song_id, format_label) if *filename* matches a legacy pattern."""
    if filename in _EXCLUDE_NAMES:
        return None
    for pattern, fmt in _LEGACY_PATTERNS:
        m = re.match(pattern, filename)
        if m:
            return int(m.group(1)), fmt
    return None


# ── Public API ───────────────────────────────────────────────────────────


def migrate(
    old_dir: str,
    new_dir: str,
    *,
    apply: bool = False,
) -> MigrationResult:
    """Scan *old_dir* for legacy jacket files and optionally copy them.

    Args:
        old_dir: Path to the legacy cache directory (read-only).
        new_dir: Path to the new cache directory.
        apply: If True, copy files and write ``manifest.json``.
               If False (default), only scan and report.

    Returns:
        MigrationResult with counts, format distribution, manifest,
        and copy/skip counters.
    """
    result = MigrationResult(
        old_dir=old_dir,
        new_dir=new_dir,
        applied=apply,
    )

    old = Path(old_dir)
    new = Path(new_dir)

    if not old.is_dir():
        print(f"Error: old-dir not found or not a directory: {old_dir}", file=sys.stderr)
        return result

    if apply:
        new.mkdir(parents=True, exist_ok=True)

    # Phase 1 — Scan
    entries: list[tuple[str, int, str, str]] = []  # (name, song_id, fmt, sha256)
    for entry in sorted(old.iterdir()):
        if not entry.is_file():
            continue
        matched = _match_legacy(entry.name)
        if matched is None:
            continue
        song_id, fmt = matched
        sha = _sha256_hex(str(entry))
        entries.append((entry.name, song_id, fmt, sha))

    result.total_files = len(entries)
    result.total_bytes = sum(
        old.joinpath(name).stat().st_size for name, _, _, _ in entries
    )
    for _, _, fmt, _ in entries:
        result.format_counts[fmt] = result.format_counts.get(fmt, 0) + 1

    # Phase 2 — Build manifest (with status placeholders)
    manifest_entries: list[dict[str, object]] = []
    for name, song_id, fmt, sha in entries:
        manifest_entries.append({
            "name": name,
            "song_id": song_id,
            "format": fmt,
            "sha256": sha,
            "status": "dry-run",
        })

    # Report
    print(f"Old dir:    {old_dir}")
    print(f"New dir:    {new_dir}")
    print(f"Mode:       {'APPLY' if apply else 'DRY-RUN (no copy)'}")
    print(f"Files:      {result.total_files}")
    print(f"Total size: {result.total_bytes / (1024*1024):.1f} MiB")
    print(f"Formats:    {result.format_counts}")
    print()

    if not apply:
        result.manifest = manifest_entries
        print("Run with --apply to copy files.")
        return result

    # Phase 3 — Apply with no-overwrite
    for i, (name, song_id, fmt, src_sha) in enumerate(entries):
        src = old / name
        dst = new / name

        if dst.exists():
            dst_sha = _sha256_hex(str(dst))
            if dst_sha == src_sha:
                manifest_entries[i]["status"] = "skipped_identical"
                result.skipped_identical += 1
            else:
                manifest_entries[i]["status"] = "skipped_conflict"
                manifest_entries[i]["existing_sha256"] = dst_sha
                result.skipped_conflict += 1
        else:
            shutil.copy2(str(src), str(dst))
            manifest_entries[i]["status"] = "copied"
            result.copied += 1

    print(f"Copied:              {result.copied}")
    print(f"Skipped (identical): {result.skipped_identical}")
    print(f"Skipped (conflict):  {result.skipped_conflict}")
    if result.skipped_conflict > 0:
        print()
        print(
            "WARNING: Some files were skipped because the target already exists "
            "with different content. Review the manifest.json for details."
        )

    result.manifest = manifest_entries

    # Write manifest
    manifest_path = new / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Manifest:            {manifest_path}")

    return result


# ── CLI ──────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Migrate legacy PJSK jacket cache to new shared layout.",
    )
    p.add_argument("--old-dir", required=True, help="Legacy cache directory (read-only).")
    p.add_argument("--new-dir", required=True, help="New cache directory.")
    p.add_argument("--apply", action="store_true", help="Actually copy files (default: dry-run).")
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    result = migrate(args.old_dir, args.new_dir, apply=args.apply)
    if result.total_files == 0:
        print("No legacy jacket files found.", file=sys.stderr)
        sys.exit(0)
