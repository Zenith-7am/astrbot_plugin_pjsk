"""Fix chart official_level from legacy song_difficulties data.

The migration backfilled HARD/NORMAL/EASY charts with mid-range default
official_level values (5/10/15). The old bot's song_difficulties table
stored the ACTUAL official level for these difficulties in its 'constant'
column (not a community constant — those only exist for MASTER/EXPERT/APPEND).

This tool reads the old DB and writes the corrected official_level to the
new DB. Only HARD, NORMAL, and EASY charts are affected. MASTER, EXPERT,
and APPEND charts are left untouched (they were correctly imported from
PENTATONIC chart_data).

Usage::

    python -m tools.fix_chart_levels <legacy.db> <new.db> [--dry-run]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def fix(legacy_path: Path, new_db_path: Path, *, dry_run: bool = False) -> dict:
    """Read old levels and apply to new DB. Returns {updated, skipped, errors}."""
    # Open old DB read-only
    ro_uri = f"file:{legacy_path.resolve()}?mode=ro"
    legacy = sqlite3.connect(ro_uri, uri=True)
    legacy.row_factory = sqlite3.Row

    # Read old official levels for HARD and below
    old_rows = legacy.execute(
        "SELECT song_id, difficulty, CAST(constant AS INTEGER) AS lv "
        "FROM song_difficulties "
        "WHERE difficulty IN ('easy', 'normal', 'hard')"
    ).fetchall()
    legacy.close()

    # Open new DB
    new_db = sqlite3.connect(str(new_db_path))
    new_db.row_factory = sqlite3.Row

    updated = 0
    skipped = 0
    errors = 0

    for row in old_rows:
        song_id = row["song_id"]
        difficulty = row["difficulty"]
        old_level = row["lv"]

        if old_level == 0:
            skipped += 1
            continue

        # Update only charts that still have the default migration value
        result = new_db.execute(
            "UPDATE charts SET official_level = ? "
            "WHERE song_id = ? AND difficulty = ? "
            "AND official_level IN (5, 10, 15)",
            (old_level, song_id, difficulty),
        )
        if result.rowcount == 0:
            skipped += 1
        else:
            updated += 1
            if updated <= 5 or updated % 200 == 0:
                print(f"  {song_id} {difficulty:6s}: {old_level}")

    if dry_run:
        new_db.rollback()
        print(f"\nDRY RUN — would update {updated} charts, skip {skipped}")
    else:
        new_db.commit()
        print(f"\nCommitted: {updated} updated, {skipped} skipped, {errors} errors")

    new_db.close()
    return {"updated": updated, "skipped": skipped, "errors": errors}


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if len(args) < 2:
        print("Usage: python -m tools.fix_chart_levels <legacy.db> <new.db> [--dry-run]",
              file=sys.stderr)
        sys.exit(2)

    legacy_path = Path(args[0])
    new_db_path = Path(args[1])

    if not legacy_path.exists():
        print(f"Legacy DB not found: {legacy_path}", file=sys.stderr)
        sys.exit(1)
    if not new_db_path.exists():
        print(f"New DB not found: {new_db_path}", file=sys.stderr)
        sys.exit(1)

    r = fix(legacy_path, new_db_path, dry_run=dry_run)

    if r["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
