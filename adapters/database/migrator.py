"""Versioned SQLite migration runner — atomic per-migration transactions."""

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


async def run_migrations(
    db_path: Path, *, migrations_dir: Path | None = None
) -> int:
    """Apply unapplied migrations in version order. Each migration runs
    inside an explicit transaction: the DDL and the schema_version INSERT
    either both succeed or both roll back.  Returns the new version."""
    if migrations_dir is None:
        migrations_dir = Path(__file__).parent / "migrations"

    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT NOT NULL,
                sha256      TEXT NOT NULL DEFAULT ''
            )
        """)
        await conn.commit()

        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        current: int = row[0] if row else 0
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            version = int(migration_file.stem.split("_")[0])
            if version <= current:
                continue

            sql = migration_file.read_text(encoding="utf-8")
            statements = _split_statements(sql)

            await conn.execute("BEGIN")
            try:
                for stmt in statements:
                    await conn.execute(stmt)
                now = datetime.now(timezone.utc).isoformat()
                file_sha = _sha256(sql)
                await conn.execute(
                    "INSERT INTO schema_version(version, applied_at, sha256) "
                    "VALUES (?, ?, ?)",
                    (version, now, file_sha),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
    finally:
        await conn.close()


def _split_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements, stripping blank lines and
    single-line `--` comments.  Does NOT handle semicolons inside string
    literals (migration files must avoid those)."""
    statements: list[str] = []
    for raw in sql.split(";"):
        # Strip leading/trailing whitespace and comment-only lines
        lines = raw.split("\n")
        non_comment = [ln for ln in lines
                       if ln.strip() and not ln.strip().startswith("--")]
        body = "\n".join(non_comment).strip()
        if body:
            statements.append(body)
    return statements


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
