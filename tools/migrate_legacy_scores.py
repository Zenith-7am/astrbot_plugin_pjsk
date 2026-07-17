"""One-shot migration: legacy emu-bot SQLite → new pjsk-astrbot schema.

Reads the old bot database read-only, creates (or reuses) the new database,
and migrates users, score history, personal bests, and identity mappings.

Usage::

    python -m tools.migrate_legacy_scores <legacy.db> <new.db> [--chart-data <dir>]

Pre-requisites:
  - ``import_chart_data`` must have been run on the new DB first
    (or pass ``--chart-data`` to run it as part of the migration).
  - The new DB must already have the schema migrations applied
    (``run_migrations`` is called automatically if ``--chart-data`` is given).

Safety:
  - The legacy DB is opened with ``mode=ro`` — no writes.
  - Writes to the new DB are wrapped in a single transaction (all-or-nothing).
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import aiosqlite

from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations

# ═══════════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════════

SOURCE_GATEWAY = "legacy_migration"
EMPTY_IMAGE_SHA256 = hashlib.sha256(b"").hexdigest()


def _derive_status(
    perfect: int, great: int, good: int, bad: int, miss: int,
) -> str:
    """Derive score status from judgement counts (domain rule §5.3)."""
    if great == 0 and good == 0 and bad == 0 and miss == 0 and perfect > 0:
        return "ap"
    if good == 0 and bad == 0 and miss == 0:
        return "fc"
    return "clear"


def _unix_to_iso(ts: int | float) -> str:
    """Convert a Unix timestamp (seconds) to ISO-8601 UTC."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _open_legacy_ro(path: Path) -> sqlite3.Connection:
    """Open the legacy database read-only."""
    ro_uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(ro_uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# read legacy data
# ═══════════════════════════════════════════════════════════════════════════════


def _read_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT qq_id, game_id, created_at, updated_at, append_excluded "
            "FROM users ORDER BY qq_id"
        ).fetchall()
    ]


def _read_songs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, title_ja, title_cn, title_en, aliases FROM songs ORDER BY id"
        ).fetchall()
    ]


def _read_song_difficulties(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Read old song_difficulties for backfilling charts not in PENTATONIC data."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT song_id, difficulty, note_count, constant, const_tag "
            "FROM song_difficulties ORDER BY song_id, difficulty"
        ).fetchall()
    ]


def _read_scores(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Read rows from *table* (``scores`` or ``score_history``)."""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT id, game_id, song_id, difficulty, "
            f"perfect, great, good, bad, miss, accuracy, power, uploaded_at "
            f"FROM [{table}] ORDER BY id"
        ).fetchall()
    ]


def _read_openid_map(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT openid, qq_id, group_openid, bound_at, last_seen_at "
            "FROM openid_map ORDER BY openid"
        ).fetchall()
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# migrate
# ═══════════════════════════════════════════════════════════════════════════════


async def _migrate_users(
    conn: aiosqlite.Connection, legacy_users: list[dict[str, Any]],
) -> dict[str, int]:
    """Insert legacy users. Returns {qq_id: new_user_id} mapping."""
    mapping: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()

    for u in legacy_users:
        qq_id = u["qq_id"]
        game_id = u.get("game_id") or None
        append_excluded = u.get("append_excluded", 1)
        created = _unix_to_iso(u["created_at"]) if u.get("created_at") else now
        updated = _unix_to_iso(u["updated_at"]) if u.get("updated_at") else now

        cursor = await conn.execute(
            "INSERT INTO users(qq_number, game_id, append_excluded, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (qq_id, game_id, append_excluded, created, updated),
        )
        if cursor.lastrowid is None:
            raise RuntimeError(f"Failed to insert user {qq_id}")
        mapping[qq_id] = cursor.lastrowid

    return mapping


async def _enrich_songs(
    conn: aiosqlite.Connection, legacy_songs: list[dict[str, Any]],
) -> int:
    """Enrich existing songs with old aliases and title_en. Returns count of updated rows."""
    updated = 0
    for s in legacy_songs:
        sid = s["id"]
        aliases = s.get("aliases", "[]")
        title_en = s.get("title_en", "")
        title_cn = s.get("title_cn", "")

        # Only update if old data has something to contribute
        has_aliases = aliases and aliases != "[]"
        has_title_en = bool(title_en)
        has_title_cn = bool(title_cn)

        if not (has_aliases or has_title_en or has_title_cn):
            continue

        # Read current values
        cur = await conn.execute(
            "SELECT title_cn, title_en, aliases FROM songs WHERE id = ?", (sid,)
        )
        row = await cur.fetchone()
        if row is None:
            continue

        new_cn = title_cn if has_title_cn and not row["title_cn"] else row["title_cn"]
        new_en = title_en if has_title_en and not row["title_en"] else row["title_en"]

        # Merge aliases: keep existing + add new unique entries
        import json as _json
        try:
            existing_aliases = set(_json.loads(row["aliases"] or "[]"))
        except Exception:
            existing_aliases = set()
        try:
            new_aliases = set(_json.loads(aliases or "[]"))
        except Exception:
            new_aliases = set()
        merged = sorted(existing_aliases | new_aliases)

        if (
            new_cn != row["title_cn"]
            or new_en != row["title_en"]
            or merged != sorted(existing_aliases)
        ):
            await conn.execute(
                "UPDATE songs SET title_cn = ?, title_en = ?, aliases = ? WHERE id = ?",
                (new_cn, new_en, _json.dumps(merged, ensure_ascii=False), sid),
            )
            updated += 1

    return updated


# Difficulty → default official_level for charts missing from PENTATONIC data
# (HARD and below don't have community constants, so we use mid-range defaults)
_DEFAULT_OFFICIAL_LEVEL: dict[str, int] = {
    "easy": 5,
    "normal": 10,
    "hard": 15,
    "expert": 26,
    "master": 31,
    "append": 31,
}


async def _backfill_missing_charts(
    conn: aiosqlite.Connection,
    legacy_difficulties: list[dict[str, Any]],
    chart_data_version: str,
) -> int:
    """Create charts for difficulties not covered by PENTATONIC data
    (e.g. HARD, NORMAL, EASY). Returns count of created charts."""
    # Get set of existing (song_id, difficulty)
    existing_rows = await conn.execute_fetchall(
        "SELECT song_id, difficulty FROM charts"
    )
    existing: set[tuple[int, str]] = {
        (r["song_id"], r["difficulty"]) for r in existing_rows
    }

    created = 0
    for sd in legacy_difficulties:
        key = (sd["song_id"], sd["difficulty"])
        if key in existing:
            continue

        note_count = sd.get("note_count", 0)
        constant = sd.get("constant", 0.0)
        const_tag = sd.get("const_tag", "")

        # Build community_constant string
        if constant and constant > 0:
            const_str = f"{constant:.1f}"
            if const_tag in ("+", "-"):
                const_str += const_tag
        else:
            const_str = "0.0"

        official_level = _DEFAULT_OFFICIAL_LEVEL.get(
            sd["difficulty"], 1
        )

        # Verify the song exists in new DB
        cur = await conn.execute(
            "SELECT 1 FROM songs WHERE id = ?", (sd["song_id"],)
        )
        if await cur.fetchone() is None:
            continue

        await conn.execute(
            """INSERT INTO charts
               (song_id, difficulty, official_level,
                community_constant, note_count, chart_data_version)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sd["song_id"], sd["difficulty"], official_level,
             const_str, note_count, chart_data_version),
        )
        created += 1
        existing.add(key)

    return created


async def _build_chart_lookup(
    conn: aiosqlite.Connection,
) -> dict[tuple[int, str], int]:
    """Build {(song_id, difficulty): chart_id} from the charts table."""
    rows = await conn.execute_fetchall(
        "SELECT id, song_id, difficulty FROM charts"
    )
    return {(r["song_id"], r["difficulty"]): r["id"] for r in rows}


async def _migrate_score_rows(
    conn: aiosqlite.Connection,
    rows: list[dict[str, Any]],
    qq_to_id: dict[str, int],
    chart_lookup: dict[tuple[int, str], int],
    *,
    is_history: bool,
) -> tuple[int, int]:
    """Insert score rows into score_attempts.

    Returns (inserted, skipped) counts.
    """
    inserted = 0
    skipped = 0
    skipped_charts: set[tuple[int, str]] = set()

    for r in rows:
        qq = r["game_id"]  # misnamed — stores QQ number
        user_id = qq_to_id.get(qq)
        if user_id is None:
            skipped += 1
            continue

        chart_key = (r["song_id"], r["difficulty"])
        chart_id = chart_lookup.get(chart_key)
        if chart_id is None:
            skipped += 1
            skipped_charts.add(chart_key)
            continue

        status = _derive_status(
            r["perfect"], r["great"], r["good"], r["bad"], r["miss"],
        )
        created = (
            _unix_to_iso(r["uploaded_at"])
            if r.get("uploaded_at")
            else datetime.now(timezone.utc).isoformat()
        )

        await conn.execute(
            """INSERT INTO score_attempts
               (user_id, chart_id, perfect, great, good, bad, miss,
                accuracy, rating, status, image_sha256, source_gateway,
                ocr_run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            (
                user_id, chart_id,
                r["perfect"], r["great"], r["good"], r["bad"], r["miss"],
                r["accuracy"], r["power"],  # power → rating
                status,
                EMPTY_IMAGE_SHA256,
                SOURCE_GATEWAY if is_history else SOURCE_GATEWAY,
                created,
            ),
        )
        inserted += 1

    if skipped_charts:
        import sys as _sys
        for ck in sorted(skipped_charts):
            print(
                f"  WARNING: chart not found for (song_id={ck[0]}, {ck[1]})",
                file=_sys.stderr,
            )

    return inserted, skipped


async def _compute_personal_bests(conn: aiosqlite.Connection) -> int:
    """Compute personal_bests from score_attempts.

    For each (user_id, chart_id), selects the best attempt:
      1. FC/AP beats CLEAR
      2. Higher rating wins
      3. Newer created_at breaks ties
    """
    await conn.execute("DELETE FROM personal_bests")

    await conn.execute(
        """INSERT INTO personal_bests
           (user_id, chart_id, best_attempt_id, accuracy, rating, status, updated_at)
           SELECT
               sa.user_id,
               sa.chart_id,
               sa.id AS best_attempt_id,
               sa.accuracy,
               sa.rating,
               sa.status,
               sa.created_at AS updated_at
           FROM score_attempts sa
           INNER JOIN (
               SELECT
                   user_id,
                   chart_id,
                   MAX(
                       CASE status
                           WHEN 'ap' THEN 3000000
                           WHEN 'fc' THEN 2000000
                           WHEN 'clear' THEN 1000000
                       END + CAST(rating * 100 AS INTEGER)
                   ) AS best_score
               FROM score_attempts
               GROUP BY user_id, chart_id
           ) ranked
               ON sa.user_id = ranked.user_id
               AND sa.chart_id = ranked.chart_id
               AND (
                   CASE sa.status
                       WHEN 'ap' THEN 3000000
                       WHEN 'fc' THEN 2000000
                       WHEN 'clear' THEN 1000000
                   END + CAST(sa.rating * 100 AS INTEGER)
               ) = ranked.best_score
           GROUP BY sa.user_id, sa.chart_id
           HAVING sa.id = MAX(sa.id)"""
    )

    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM personal_bests")
    row = await cur.fetchone()
    return row["cnt"] if row else 0


async def _migrate_openid_map(
    conn: aiosqlite.Connection,
    rows: list[dict[str, Any]],
    qq_to_id: dict[str, int],
) -> int:
    """Migrate openid_map → external_identities. Returns count inserted."""
    inserted = 0
    for r in rows:
        qq = r["qq_id"]
        user_id = qq_to_id.get(qq)
        if user_id is None:
            continue
        bound = _unix_to_iso(r["bound_at"]) if r.get("bound_at") else datetime.now(timezone.utc).isoformat()
        await conn.execute(
            "INSERT INTO external_identities(user_id, platform, external_id, created_at) "
            "VALUES (?, 'qq_official', ?, ?)",
            (user_id, r["openid"], bound),
        )
        inserted += 1
    return inserted


# ═══════════════════════════════════════════════════════════════════════════════
# reconcile
# ═══════════════════════════════════════════════════════════════════════════════

class ReconcileReport(NamedTuple):
    users: int
    score_attempts: int
    personal_bests: int
    external_identities: int
    songs_enriched: int
    warnings: list[str]


async def _reconcile(
    conn: aiosqlite.Connection,
    expected_users: int,
    expected_history: int,
    expected_scores: int,
    expected_openid: int,
    inserted_history: int,
    inserted_scores: int,
    skipped_history: int,
    skipped_scores: int,
    songs_enriched: int,
    pb_count: int,
    openid_inserted: int,
) -> ReconcileReport:
    """Produce a reconciliation report."""
    warnings: list[str] = []

    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM users")
    row = await cur.fetchone()
    actual_users: int = row["cnt"] if row else 0
    if actual_users != expected_users:
        warnings.append(
            f"Users: expected {expected_users}, got {actual_users}"
        )

    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM score_attempts")
    row = await cur.fetchone()
    actual_attempts: int = row["cnt"] if row else 0
    expected_attempts = (inserted_history + inserted_scores)
    if actual_attempts != expected_attempts:
        warnings.append(
            f"Score attempts: expected {expected_attempts}, got {actual_attempts}"
        )

    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM personal_bests")
    row = await cur.fetchone()
    actual_pb: int = row["cnt"] if row else 0

    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM external_identities")
    row = await cur.fetchone()
    actual_ext: int = row["cnt"] if row else 0

    # Check for orphan score_attempts
    orphan_attempts_cur = list(await conn.execute_fetchall(
        "SELECT COUNT(*) AS cnt FROM score_attempts sa "
        "LEFT JOIN users u ON sa.user_id = u.id WHERE u.id IS NULL"
    ))
    orphan_attempts = orphan_attempts_cur[0]["cnt"]
    if orphan_attempts > 0:
        warnings.append(f"Orphan score_attempts (no user): {orphan_attempts}")

    orphan_pb_cur = list(await conn.execute_fetchall(
        "SELECT COUNT(*) AS cnt FROM personal_bests pb "
        "LEFT JOIN users u ON pb.user_id = u.id WHERE u.id IS NULL"
    ))
    orphan_pb = orphan_pb_cur[0]["cnt"]
    if orphan_pb > 0:
        warnings.append(f"Orphan personal_bests (no user): {orphan_pb}")

    return ReconcileReport(
        users=actual_users,
        score_attempts=actual_attempts,
        personal_bests=actual_pb,
        external_identities=actual_ext,
        songs_enriched=songs_enriched,
        warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# public API
# ═══════════════════════════════════════════════════════════════════════════════


async def migrate(
    legacy_path: Path,
    new_db_path: Path,
    *,
    chart_data_dir: Path | None = None,
) -> ReconcileReport:
    """Run the full legacy migration.

    Args:
        legacy_path: Path to the old emu-bot ``bot.db``.
        new_db_path: Path to the new (target) database.
        chart_data_dir: If given, ``import_chart_data`` is run before
            migration.  Required on the first run; safe to skip on re-runs.
    """
    if not legacy_path.exists():
        raise FileNotFoundError(f"Legacy database not found: {legacy_path}")

    legacy = _open_legacy_ro(legacy_path)

    # ── Read all legacy data upfront ──────────────────────────────────────
    legacy_users = _read_users(legacy)
    legacy_songs = _read_songs(legacy)
    legacy_difficulties = _read_song_difficulties(legacy)
    legacy_history = _read_scores(legacy, "score_history")
    legacy_scores = _read_scores(legacy, "scores")
    legacy_openid = _read_openid_map(legacy)
    legacy.close()

    print(f"Legacy DB read: {len(legacy_users)} users, "
          f"{len(legacy_songs)} songs, "
          f"{len(legacy_difficulties)} song_difficulties, "
          f"{len(legacy_scores)} scores (best), "
          f"{len(legacy_history)} score_history, "
          f"{len(legacy_openid)} openid_map")

    # ── Prepare new database ──────────────────────────────────────────────
    chart_data_version = "legacy"
    if chart_data_dir is not None:
        from tools.import_chart_data import import_chart_data
        await run_migrations(new_db_path)
        chart_result = await import_chart_data(new_db_path, chart_data_dir)
        chart_data_version = "2026-07-12"  # matches chart_data/manifest.json
        print(f"Chart data imported: {chart_result}")

    conn = await get_connection(new_db_path)

    try:
        await conn.execute("BEGIN")

        # ── Backfill missing charts (HARD and below, not in PENTATONIC) ──
        backfilled = await _backfill_missing_charts(
            conn, legacy_difficulties, chart_data_version,
        )
        if backfilled:
            print(f"Charts backfilled (HARD and below): {backfilled}")

        # ── Users ─────────────────────────────────────────────────────────
        qq_to_id = await _migrate_users(conn, legacy_users)
        print(f"Users migrated: {len(qq_to_id)}")

        # ── Songs enrichment ──────────────────────────────────────────────
        songs_enriched = await _enrich_songs(conn, legacy_songs)
        if songs_enriched:
            print(f"Songs enriched (aliases/titles): {songs_enriched}")

        # ── Build chart lookup ────────────────────────────────────────────
        chart_lookup = await _build_chart_lookup(conn)
        print(f"Charts available: {len(chart_lookup)}")

        # ── Score history → score_attempts ────────────────────────────────
        hist_inserted, hist_skipped = await _migrate_score_rows(
            conn, legacy_history, qq_to_id, chart_lookup, is_history=True,
        )
        print(f"Score history migrated: {hist_inserted} inserted, "
              f"{hist_skipped} skipped")

        # ── Scores (old bests) → score_attempts ───────────────────────────
        score_inserted, score_skipped = await _migrate_score_rows(
            conn, legacy_scores, qq_to_id, chart_lookup, is_history=False,
        )
        print(f"Scores (old bests) migrated: {score_inserted} inserted, "
              f"{score_skipped} skipped")

        # ── Personal bests ────────────────────────────────────────────────
        pb_count = await _compute_personal_bests(conn)
        print(f"Personal bests computed: {pb_count}")

        # ── External identities ───────────────────────────────────────────
        ext_inserted = await _migrate_openid_map(conn, legacy_openid, qq_to_id)
        if ext_inserted:
            print(f"External identities migrated: {ext_inserted}")

        # ── Reconcile ─────────────────────────────────────────────────────
        report = await _reconcile(
            conn,
            expected_users=len(legacy_users),
            expected_history=len(legacy_history),
            expected_scores=len(legacy_scores),
            expected_openid=len(legacy_openid),
            inserted_history=hist_inserted,
            inserted_scores=score_inserted,
            skipped_history=hist_skipped,
            skipped_scores=score_skipped,
            songs_enriched=songs_enriched,
            pb_count=pb_count,
            openid_inserted=ext_inserted,
        )

        if report.warnings:
            print("\n⚠ Warnings:")
            for w in report.warnings:
                print(f"  - {w}")
            # Rollback on warnings — migration should be clean
            await conn.rollback()
            print("\nMigration ROLLED BACK due to warnings.")
            return report

        await conn.commit()
        print("\nMigration COMMITTED successfully.")

        print("\nReconcile report:")
        print(f"  users:              {report.users}")
        print(f"  score_attempts:     {report.score_attempts}")
        print(f"  personal_bests:     {report.personal_bests}")
        print(f"  external_identities:{report.external_identities}")
        print(f"  songs enriched:     {report.songs_enriched}")
        print(f"  warnings:           {len(report.warnings)}")

        return report

    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Migrate legacy emu-bot SQLite → new pjsk-astrbot schema",
    )
    parser.add_argument(
        "legacy_db", type=Path,
        help="Path to the old emu-bot bot.db",
    )
    parser.add_argument(
        "new_db", type=Path,
        help="Path to the new (target) database",
    )
    parser.add_argument(
        "--chart-data", type=Path, default=None,
        help="Path to chart_data/ directory (runs import_chart_data before migration)",
    )
    args = parser.parse_args()

    report = asyncio.run(
        migrate(args.legacy_db, args.new_db, chart_data_dir=args.chart_data)
    )

    if report.warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
