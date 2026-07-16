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

The old directory is **never modified or deleted**.  Files are copied
with their original extensions (format distribution is preserved for
audit trail).  A ``manifest.json`` listing every copied file and its
SHA-256 is written to the new directory on ``--apply``.
"""

from __future__ import annotations

import argparse
import hashlib
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


# ── Pattern matching ─────────────────────────────────────────────────────

# (regex, format_label)
_LEGACY_PATTERNS: list[tuple[str, str]] = [
    (r"^jacket_s_(\d{3})\.png$", "png"),
    (r"^(\d{3})\.png$",           "png"),
    (r"^(\d{3})\.jpg$",           "jpg"),
    (r"^(\d+)\.jpg$",             "jpg"),
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
        MigrationResult with counts, format distribution, and manifest.
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

    # Scan
    entries: list[tuple[str, int, str]] = []  # (filename, song_id, format)
    for entry in sorted(old.iterdir()):
        if not entry.is_file():
            continue
        matched = _match_legacy(entry.name)
        if matched is None:
            continue
        song_id, fmt = matched
        entries.append((entry.name, song_id, fmt))

    result.total_files = len(entries)
    result.total_bytes = sum(
        old.joinpath(name).stat().st_size for name, _, _ in entries
    )
    for _, _, fmt in entries:
        result.format_counts[fmt] = result.format_counts.get(fmt, 0) + 1

    # Build manifest
    for name, song_id, fmt in entries:
        src = old / name
        sha = _sha256_hex(str(src))
        result.manifest.append({
            "name": name,
            "song_id": song_id,
            "format": fmt,
            "sha256": sha,
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
        print("Run with --apply to copy files.")
        return result

    # Copy
    copied = 0
    for name, song_id, fmt in entries:
        src = old / name
        dst = new / name
        shutil.copy2(str(src), str(dst))
        copied += 1

    print(f"Copied:     {copied} files")

    # Write manifest
    import json
    manifest_path = new / "manifest.json"
    manifest_path.write_text(
        json.dumps(result.manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Manifest:   {manifest_path}")

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
