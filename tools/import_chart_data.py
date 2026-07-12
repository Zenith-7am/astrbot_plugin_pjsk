"""Import chart constant data from JSON files into SQLite.

Verifies SHA-256 of each data file against manifest before touching the
database.  All validation runs ahead of any write — a single bad file
rejects the entire batch.  Existing charts are updated when any field
changes, so subsequent data-version imports correctly overwrite stale
community constants, note counts, and official levels.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations

_VALID_DIFFICULTIES = {"easy", "normal", "hard", "expert", "master", "append"}
_CONSTANT_RE = re.compile(r"^\d+\.\d[+-]?$")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_manifest(data_dir: Path) -> tuple[str, dict[str, str]]:
    """Return (version, {filename: expected_sha256}) from manifest.json.

    Raises FileNotFoundError if manifest or a listed file is missing.
    """
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version: str = manifest["version"]
    files: dict[str, str] = manifest["files"]

    for filename in files:
        if not (data_dir / filename).exists():
            raise FileNotFoundError(
                f"Data file listed in manifest not found: {data_dir / filename}"
            )
    return version, files


def _read_and_verify(data_dir: Path, files: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Read every data file, verify its SHA-256, and return parsed contents.

    Raises ValueError on any hash mismatch.
    """
    result: dict[str, dict[str, Any]] = {}
    for filename, expected_hash in files.items():
        raw = (data_dir / filename).read_bytes()
        actual_hash = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if actual_hash != expected_hash:
            raise ValueError(
                f"SHA-256 mismatch for {filename}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        result[filename] = json.loads(raw.decode("utf-8"))
    return result


def _validate_charts(file_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate every chart across all files.  Returns a flat list of
    validated chart dicts ready for insertion.

    Raises ValueError on any invalid difficulty, constant format, or
    note_count (rejects the *entire* batch — no silent skip).
    """
    charts: list[dict[str, Any]] = []
    for filename, data in file_data.items():
        for chart in data.get("charts", []):
            diff = chart["difficulty"]
            if diff not in _VALID_DIFFICULTIES:
                raise ValueError(
                    f"Invalid difficulty {diff!r} in {filename} "
                    f"for song_id={chart.get('song_id', '?')}"
                )
            if not _CONSTANT_RE.match(chart["community_constant"]):
                raise ValueError(
                    f"Invalid constant format {chart['community_constant']!r} "
                    f"in {filename} for song_id={chart['song_id']}"
                )
            if chart["note_count"] <= 0:
                raise ValueError(
                    f"note_count must be positive in {filename} "
                    f"for song_id={chart['song_id']}"
                )
            charts.append(chart)
    return charts


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def import_chart_data(db_path: Path, data_dir: Path) -> dict[str, int]:
    """Import all chart data files listed in manifest.json.

    1. Validate manifest and every data file (SHA-256 + field checks)
       *before* opening the database — a bad file never touches SQLite.
    2. Upsert songs and charts so subsequent data-version imports
       correctly update stale values.
    3. Return ``{"inserted": N, "updated": N, "unchanged": N}``.
    """
    version, file_hashes = _parse_manifest(data_dir)
    file_data = _read_and_verify(data_dir, file_hashes)
    validated = _validate_charts(file_data)

    await run_migrations(db_path)

    conn = await get_connection(db_path)
    result: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}

    try:
        for chart in validated:
            song_id = chart["song_id"]
            difficulty = chart["difficulty"]
            title_ja = chart["title_ja"]
            title_cn = chart.get("title_cn", "")
            official_level = chart["official_level"]
            community_constant = chart["community_constant"]
            note_count = chart["note_count"]

            # --- song: upsert so new versions can amend titles ------------
            await conn.execute(
                """INSERT INTO songs(id, title_ja, title_cn)
                   VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       title_ja = excluded.title_ja,
                       title_cn = excluded.title_cn""",
                (song_id, title_ja, title_cn),
            )

            # --- chart: detect insert / update / unchanged ----------------
            cur = await conn.execute(
                """SELECT community_constant, official_level, note_count
                   FROM charts WHERE song_id = ? AND difficulty = ?""",
                (song_id, difficulty),
            )
            existing = await cur.fetchone()

            if existing is None:
                await conn.execute(
                    """INSERT INTO charts
                       (song_id, difficulty, official_level,
                        community_constant, note_count, chart_data_version)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (song_id, difficulty, official_level,
                     community_constant, note_count, version),
                )
                result["inserted"] += 1
            else:
                old_constant, old_level, old_notes = existing
                if (old_constant != community_constant
                        or old_level != official_level
                        or old_notes != note_count):
                    await conn.execute(
                        """UPDATE charts SET
                           official_level = ?, community_constant = ?,
                           note_count = ?, chart_data_version = ?
                           WHERE song_id = ? AND difficulty = ?""",
                        (official_level, community_constant,
                         note_count, version, song_id, difficulty),
                    )
                    result["updated"] += 1
                else:
                    # Still bump chart_data_version so the version column
                    # reflects the last import that touched this row.
                    await conn.execute(
                        """UPDATE charts SET chart_data_version = ?
                           WHERE song_id = ? AND difficulty = ?""",
                        (version, song_id, difficulty),
                    )
                    result["unchanged"] += 1

        await conn.commit()
        return result
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()
