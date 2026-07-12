"""Versioned SQLite migration runner — atomic per-migration transactions
with startup SHA-256 re-verification of previously-applied migrations."""

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


async def run_migrations(
    db_path: Path, *, migrations_dir: Path | None = None
) -> int:
    """Apply unapplied migrations in version order. Each migration runs
    inside an explicit transaction: the DDL and the schema_version INSERT
    either both succeed or both roll back.

    Before applying new migrations, re-verifies the SHA-256 of every
    already-applied migration against the file on disk — a mismatch means
    the migration has been modified since it was applied and raises
    ``RuntimeError``.  Returns the new (or current) schema version."""
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

        # --- re-verify already-applied SHA-256 ---------------------------
        applied_rows = list(
            await conn.execute_fetchall(
                "SELECT version, sha256 FROM schema_version ORDER BY version"
            )
        )
        for ver, stored_sha in applied_rows:
            file_path = _migration_file(migrations_dir, ver)
            if not file_path.exists():
                raise RuntimeError(
                    f"Migration file for version {ver} is missing: {file_path}"
                )
            sql = file_path.read_text(encoding="utf-8")
            current_sha = _sha256(sql)
            if current_sha != stored_sha:
                raise RuntimeError(
                    f"SHA-256 mismatch for already-applied migration {ver} "
                    f"(stored: {stored_sha[:16]}…, current: {current_sha[:16]}…). "
                    f"The migration file has been modified — rejecting startup."
                )
        # -----------------------------------------------------------------

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
        return int(row[0]) if row else 0
    finally:
        await conn.close()


def _migration_file(migrations_dir: Path, version: int) -> Path:
    """Find the migration file for *version*."""
    for f in sorted(migrations_dir.glob("*.sql")):
        if int(f.stem.split("_")[0]) == version:
            return f
    raise RuntimeError(
        f"No migration file found for version {version}"
    )


def _split_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements, stripping blank lines and
    single-line ``--`` comments.  Does NOT handle semicolons inside string
    literals (migration files must avoid those)."""
    statements: list[str] = []
    for raw in sql.split(";"):
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
