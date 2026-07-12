"""Read-only legacy database auditor.

Opens a SQLite copy with mode=ro, reports aggregate schema and integrity
statistics, and NEVER emits raw row values (QQ numbers, game IDs, OCR text).
"""

import hashlib
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_TABLES = ("users", "scores", "score_history", "songs", "song_difficulties", "ocr_records")


@dataclass
class AuditReport:
    """Aggregate-only audit result.  No user-level data."""

    tables: dict[str, int] = field(default_factory=dict)
    columns: dict[str, list[str]] = field(default_factory=dict)
    duplicate_game_ids: int = 0
    orphan_scores: int = 0
    qq_score_linkage: int = 0
    null_identity_count: int = 0
    invalid_scores: int = 0
    min_timestamp: int | None = None
    max_timestamp: int | None = None
    source_sha256: str = ""
    unrecognized_tables: list[str] = field(default_factory=list)


def audit_database(path: Path) -> AuditReport:
    """Audit a legacy emu-bot database snapshot (read-only).

    Returns an AuditReport with aggregate statistics only.
    SystemExit(1) if any required table is missing.
    """
    if not path.exists():
        print(f"Database not found: {path}", file=sys.stderr)
        sys.exit(1)

    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    # Open read-only — the URI must be an absolute path
    ro_uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(ro_uri, uri=True)

    report = AuditReport(source_sha256=source_sha256)

    # ── Discover all tables ──
    table_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    existing = {r[0] for r in table_rows}

    # Required tables check
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        print(f"Missing required tables: {', '.join(missing)}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    report.unrecognized_tables = sorted(existing - set(REQUIRED_TABLES))

    # ── Per-table stats ──
    for table_name in sorted(existing):
        # Row count
        count = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
        report.tables[table_name] = count

        # Columns
        cols = conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()
        report.columns[table_name] = [c[1] for c in cols]

    # ── Integrity checks ──

    # Duplicate game_ids (same game_id assigned to multiple qq_id)
    dupes = conn.execute("""
        SELECT game_id, COUNT(*) AS cnt FROM users
        WHERE game_id IS NOT NULL AND game_id != ''
        GROUP BY game_id HAVING cnt > 1
    """).fetchall()
    report.duplicate_game_ids = len(dupes)

    # Orphan scores (scores.game_id is QQ number — check against users.qq_id)
    orphans = conn.execute("""
        SELECT COUNT(*) FROM scores
        WHERE game_id NOT IN (SELECT qq_id FROM users)
    """).fetchone()[0]
    report.orphan_scores = orphans

    # QQ-to-score linkage coverage
    linked = conn.execute("""
        SELECT COUNT(*) FROM scores s
        JOIN users u ON s.game_id = u.qq_id
    """).fetchone()[0]
    report.qq_score_linkage = linked

    # Null PJSK game_ids (users.game_id is separate field, often unset)
    null_ids = conn.execute("""
        SELECT COUNT(*) FROM users
        WHERE game_id IS NULL OR game_id = ''
    """).fetchone()[0]
    report.null_identity_count = null_ids

    # Invalid scores (negative judgement counts)
    invalid = conn.execute("""
        SELECT COUNT(*) FROM scores
        WHERE perfect < 0 OR great < 0 OR good < 0 OR bad < 0 OR miss < 0
    """).fetchone()[0]
    report.invalid_scores = invalid

    # Also check score_history
    invalid_hist = conn.execute("""
        SELECT COUNT(*) FROM score_history
        WHERE perfect < 0 OR great < 0 OR good < 0 OR bad < 0 OR miss < 0
    """).fetchone()[0]
    report.invalid_scores += invalid_hist

    # ── Timestamp range ──
    timestamps: list[int] = []
    for table, col in [("users", "created_at"), ("scores", "uploaded_at"), ("score_history", "uploaded_at")]:
        try:
            rows = conn.execute(
                f"SELECT {col} FROM [{table}] WHERE {col} IS NOT NULL"
            ).fetchall()
            timestamps.extend(r[0] for r in rows)
        except sqlite3.OperationalError:
            pass

    if timestamps:
        report.min_timestamp = min(timestamps)
        report.max_timestamp = max(timestamps)

    conn.close()
    return report


def main() -> None:
    """CLI entry point: audit a legacy database and print JSON summary.

    Usage: python -m tools.audit_legacy_db <db_path>
    """
    if len(sys.argv) < 2:
        print("Usage: python -m tools.audit_legacy_db <db_path>", file=sys.stderr)
        sys.exit(2)

    db_path = Path(sys.argv[1])
    report = audit_database(db_path)

    # Print aggregate JSON — deliberately excludes per-row data
    import json
    output = {
        "source_sha256": report.source_sha256,
        "tables": report.tables,
        "columns": report.columns,
        "integrity": {
            "duplicate_game_ids": report.duplicate_game_ids,
            "orphan_scores": report.orphan_scores,
            "null_identity_count": report.null_identity_count,
            "invalid_scores": report.invalid_scores,
        },
        "timestamp_range": {
            "min": report.min_timestamp,
            "max": report.max_timestamp,
        },
        "unrecognized_tables": report.unrecognized_tables,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
