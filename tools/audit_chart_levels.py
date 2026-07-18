"""Audit charts with default official_level values from legacy migration.

Reports charts whose official_level was assigned a mid-range default because
no authoritative source (PENTATONIC, game data) provides real levels for
HARD, NORMAL, and EASY difficulties.

Usage::

    python -m tools.audit_chart_levels <pjsk.db>

This is a read-only audit — it never writes to the database.
"""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Default levels used by tools/migrate_legacy_scores.py backfill
_DEFAULT_LEVELS: dict[str, int] = {
    "easy": 5, "normal": 10, "hard": 15,
    "expert": 26, "master": 31, "append": 31,
}


@dataclass
class AuditResult:
    affected_charts: int = 0
    affected_attempts: int = 0
    affected_pbs: int = 0
    affected_users: int = 0
    by_difficulty: dict[str, int] = field(default_factory=dict)
    by_level: dict[int, int] = field(default_factory=dict)


def audit(db_path: Path) -> AuditResult:
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    result = AuditResult()

    default_levels = tuple(set(_DEFAULT_LEVELS.values()))

    # Charts with default levels
    rows = conn.execute(
        "SELECT difficulty, official_level, COUNT(*) AS cnt "
        "FROM charts WHERE official_level IN (?, ?, ?, ?, ?) "
        "GROUP BY difficulty, official_level",
        default_levels,
    ).fetchall()
    for difficulty, level, cnt in rows:
        result.by_difficulty[difficulty] = cnt
        result.by_level[level] = result.by_level.get(level, 0) + cnt
        result.affected_charts += cnt

    # PBs linked to affected charts
    row = conn.execute(
        "SELECT COUNT(DISTINCT pb.user_id) AS users, COUNT(*) AS pb_count "
        "FROM personal_bests pb "
        "JOIN charts c ON pb.chart_id = c.id "
        "WHERE c.official_level IN (?, ?, ?, ?, ?)",
        default_levels,
    ).fetchone()
    result.affected_users = row[0]
    result.affected_pbs = row[1]

    # Score attempts on affected charts
    row = conn.execute(
        "SELECT COUNT(*) FROM score_attempts sa "
        "JOIN charts c ON sa.chart_id = c.id "
        "WHERE c.official_level IN (?, ?, ?, ?, ?)",
        default_levels,
    ).fetchone()
    result.affected_attempts = row[0]

    conn.close()
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m tools.audit_chart_levels <pjsk.db>", file=sys.stderr)
        sys.exit(2)

    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    r = audit(db_path)

    print("=== Charts with default official_level (migration backfill) ===\n")
    print(f"Affected charts:   {r.affected_charts}")
    print(f"Affected attempts: {r.affected_attempts}")
    print(f"Affected PBs:      {r.affected_pbs}")
    print(f"Affected users:    {r.affected_users}")
    print()
    print("By difficulty:")
    for diff in ["easy", "normal", "hard"]:
        count = r.by_difficulty.get(diff, 0)
        default = _DEFAULT_LEVELS[diff]
        print(f"  {diff:8s}: {count:4d} charts (all level={default})")
    print()
    print("NOTE: This is a known limitation.")
    print("PENTATONIC chart_data only covers MASTER, EXPERT, and APPEND.")
    print("HARD, NORMAL, EASY have no community constants — their official_level")
    print("defaults are mid-range estimates. Fixing requires an external game")
    print("data source (e.g., Sekai-World musicDifficulties.json).")


if __name__ == "__main__":
    main()
