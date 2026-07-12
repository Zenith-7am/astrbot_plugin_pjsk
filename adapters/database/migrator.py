"""Versioned SQLite migration runner."""
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


async def run_migrations(db_path: Path) -> int:
    """Apply unapplied migrations in version order. Returns new version."""
    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)
        await conn.commit()

        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        current: int = row[0] if row else 0

        migrations_dir = Path(__file__).parent / "migrations"
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            version = int(migration_file.stem.split("_")[0])
            if version <= current:
                continue
            sql = migration_file.read_text(encoding="utf-8")
            await conn.executescript(sql)
            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, now),
            )
            await conn.commit()

        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
    finally:
        await conn.close()
