"""Import chart constant data from JSON files into SQLite."""
import json
import re
from pathlib import Path

from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations

_VALID_DIFFICULTIES = {"easy", "normal", "hard", "expert", "master", "append"}
_CONSTANT_RE = re.compile(r"^\d+\.\d[+-]?$")


async def import_chart_data(db_path: Path, data_dir: Path) -> int:
    """Import all chart data files listed in manifest.json. Returns count of
    charts imported (skips already-present song_id+difficulty pairs)."""
    await run_migrations(db_path)
    conn = await get_connection(db_path)

    manifest = json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )
    version = manifest["version"]
    imported = 0

    try:
        for filename in manifest["files"]:
            data = json.loads(
                (data_dir / filename).read_text(encoding="utf-8")
            )
            for chart in data.get("charts", []):
                # Validation
                if chart["difficulty"] not in _VALID_DIFFICULTIES:
                    continue
                if not _CONSTANT_RE.match(chart["community_constant"]):
                    raise ValueError(
                        f"Invalid constant format: {chart['community_constant']} "
                        f"for song {chart['song_id']}"
                    )
                if chart["note_count"] <= 0:
                    raise ValueError(
                        f"note_count must be positive for song {chart['song_id']}"
                    )

                # Upsert song
                await conn.execute(
                    """INSERT OR IGNORE INTO songs(id, title_ja, title_cn)
                       VALUES (?, ?, ?)""",
                    (chart["song_id"], chart["title_ja"],
                     chart.get("title_cn", "")),
                )

                # Insert chart (skip if exists)
                cursor = await conn.execute(
                    """INSERT OR IGNORE INTO charts
                       (song_id, difficulty, official_level, community_constant,
                        note_count, chart_data_version)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        chart["song_id"], chart["difficulty"],
                        chart["official_level"], chart["community_constant"],
                        chart["note_count"], version,
                    ),
                )
                if cursor.rowcount > 0:
                    imported += 1

        await conn.commit()
        return imported
    finally:
        await conn.close()
