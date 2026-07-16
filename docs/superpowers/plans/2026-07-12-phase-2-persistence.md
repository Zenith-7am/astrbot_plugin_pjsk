> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Phase 2: Chart Data and Persistence Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish Git-versioned chart constant data, SQLite schema with versioned migrations, and SQLite-backed Repository adapters so the plugin can read and write real data.

**Architecture:** Bottom-up: chart data files → migration system → schema DDL → Repository implementations. Each Repository is tested against the Phase 1 port contract with a real SQLite backend.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), aiosqlite, pytest, pytest-asyncio, ruff, mypy strict.

## Global Constraints

- Repository methods return domain objects, never dicts or SQLite rows.
- `record_attempt` inserts attempt + updates personal_best in one transaction.
- Schema changes use explicit versioned migration scripts, never implicit DDL at startup.
- Timestamps are ISO 8601 strings in SQLite; Repository converts to/from `datetime`.
- Tests use `:memory:` SQLite — no filesystem dependency.
- Ruff + mypy strict must pass at end of every task.
- Every task ends in a focused commit.

## Dependencies

```
Task 1 (chart_data files)
  ↓
Task 2 (migration system + schema)
  ↓
Task 3 (UserRepository) ──┐
Task 4 (ChartRepository) ─┼── all depend on Task 2 schema
Task 5 (ScoreRepository) ─┘
  ↓
Task 6 (import tool) ── depends on Task 4 + chart_data files
  ↓
Task 7 (final verification)
```

---

### Task 1: Chart Data Files and Manifest

**Files:**
- Create: `chart_data/manifest.json`
- Create: `chart_data/pentatonic_master.json`
- Create: `chart_data/pentatonic_append.json`
- Create: `chart_data/pentatonic_expert.json`

**Interfaces:**
- Produces: Versioned JSON data files with validated structure. No code — pure data.

- [ ] **Step 1: Create manifest.json skeleton**

```json
{
  "version": "2026-07-12",
  "source": "PENTATONIC",
  "files": {}
}
```

- [ ] **Step 2: Create three JSON data files with `song_id: 0` placeholder entries**

Each file uses this schema:
```json
{
  "version": "2026-07-12",
  "source": "PENTATONIC",
  "charts": []
}
```

`pentatonic_master.json`, `pentatonic_append.json`, `pentatonic_expert.json` — all start with empty `charts` arrays. Real data will be populated from the legacy DB in Task 6.

- [ ] **Step 3: Verify JSON parses and schema is correct**

Run:
```python
import json
from pathlib import Path

for f in ["pentatonic_master.json", "pentatonic_append.json", "pentatonic_expert.json"]:
    data = json.loads(Path(f"chart_data/{f}").read_text(encoding="utf-8"))
    assert "version" in data
    assert "charts" in data
    assert isinstance(data["charts"], list)
```

- [ ] **Step 4: Commit**

Run: `git add chart_data/ && git commit -m "feat: add chart data file skeleton with manifest"`

---

### Task 2: Migration System and Initial Schema

**Files:**
- Create: `adapters/database/__init__.py`
- Create: `adapters/database/connection.py`
- Create: `adapters/database/migrator.py`
- Create: `adapters/database/migrations/001_initial_schema.sql`
- Create: `tests/adapters/__init__.py`
- Create: `tests/adapters/database/__init__.py`
- Create: `tests/adapters/database/test_migrator.py`
- Modify: `pyproject.toml` — add `aiosqlite` dependency

**Interfaces:**
- Produces: `get_connection(db_path) -> aiosqlite.Connection`, `run_migrations(db_path) -> int`

- [ ] **Step 1: Add aiosqlite dependency**

Edit `pyproject.toml`, add to `dependencies`:
```toml
dependencies = ["aiosqlite>=0.20"]
```

Then: `.venv\Scripts\python -m pip install -e ".[dev]"`

- [ ] **Step 2: Write failing migration test**

Create `tests/adapters/database/test_migrator.py`:

```python
"""Tests for the versioned migration system."""
import sqlite3
from pathlib import Path

import pytest
from adapters.database.migrator import run_migrations


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


class TestRunMigrations:
    def test_creates_schema_version_table(self, temp_db: Path) -> None:
        run_migrations(temp_db)
        conn = sqlite3.connect(str(temp_db))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert ("schema_version",) in tables

    def test_applies_initial_migration(self, temp_db: Path) -> None:
        run_migrations(temp_db)
        conn = sqlite3.connect(str(temp_db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected = {"schema_version", "users", "external_identities",
                    "songs", "charts", "score_attempts", "personal_bests"}
        assert expected <= tables
        conn.close()

    def test_records_migration_version(self, temp_db: Path) -> None:
        version = run_migrations(temp_db)
        assert version == 1
        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        conn.close()
        assert row == (1,)

    def test_idempotent_second_run(self, temp_db: Path) -> None:
        run_migrations(temp_db)
        version = run_migrations(temp_db)
        assert version == 1  # already applied, no change

    def test_empty_db_returns_zero(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        db.touch()
        version = run_migrations(db)
        assert version == 1  # migrations applied on empty db
```

- [ ] **Step 3: Run tests — expect import error**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_migrator.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: Implement connection.py**

```python
"""SQLite connection factory."""
from pathlib import Path

import aiosqlite


async def get_connection(db_path: Path) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

- [ ] **Step 5: Create migration 001 SQL**

Create `adapters/database/migrations/001_initial_schema.sql`:

```sql
-- 001: Initial schema — users, songs, charts, scores, personal_bests

CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qq_number  TEXT NOT NULL UNIQUE,
    game_id    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE external_identities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    platform    TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE TABLE songs (
    id       INTEGER PRIMARY KEY,
    title_ja TEXT NOT NULL,
    title_cn TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT ''
);

CREATE TABLE charts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id            INTEGER NOT NULL REFERENCES songs(id),
    difficulty         TEXT NOT NULL,
    official_level     INTEGER NOT NULL,
    community_constant TEXT NOT NULL,
    note_count         INTEGER NOT NULL,
    chart_data_version TEXT NOT NULL,
    UNIQUE(song_id, difficulty)
);

CREATE TABLE score_attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    chart_id       INTEGER NOT NULL REFERENCES charts(id),
    perfect        INTEGER NOT NULL,
    great          INTEGER NOT NULL,
    good           INTEGER NOT NULL,
    bad            INTEGER NOT NULL,
    miss           INTEGER NOT NULL,
    accuracy       REAL NOT NULL,
    rating         REAL NOT NULL,
    status         TEXT NOT NULL,
    image_sha256   TEXT NOT NULL,
    source_gateway TEXT NOT NULL,
    ocr_run_id     INTEGER,
    created_at     TEXT NOT NULL
);

CREATE TABLE personal_bests (
    user_id         INTEGER NOT NULL REFERENCES users(id),
    chart_id        INTEGER NOT NULL REFERENCES charts(id),
    best_attempt_id INTEGER NOT NULL REFERENCES score_attempts(id),
    accuracy        REAL NOT NULL,
    rating          REAL NOT NULL,
    status          TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY(user_id, chart_id)
);
```

- [ ] **Step 6: Implement migrator.py**

```python
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

        rows = await conn.execute_fetchall(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        current: int = rows[0][0] if rows else 0

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

        rows = await conn.execute_fetchall(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        return rows[0][0] if rows else 0
    finally:
        await conn.close()
```

- [ ] **Step 7: Run focused tests**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_migrator.py -v`
Expected: 5 passed

- [ ] **Step 8: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core adapters tools tests`

- [ ] **Step 9: Commit**

Run: `git add adapters/database/ tests/adapters/ pyproject.toml && git commit -m "feat: add migration system and initial SQLite schema"`

---

### Task 3: UserRepository SQLite Implementation

**Files:**
- Create: `adapters/database/repository.py`
- Create: `tests/adapters/database/test_user_repository.py`

**Interfaces:**
- Consumes: `UserRepository` Protocol from Phase 1 (`pjsk_core.ports.repositories`), domain types `UserId`, `QqNumber`, `User` from `pjsk_core.domain.users`
- Produces: `SqliteUserRepository` class implementing `UserRepository`

- [ ] **Step 1: Write failing tests**

Create `tests/adapters/database/test_user_repository.py`:

```python
"""SQLite UserRepository contract tests."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteUserRepository
from pjsk_core.domain.users import QqNumber, User, UserId


@pytest.fixture
async def repo(tmp_path: Path):
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteUserRepository(conn)
    finally:
        await conn.close()


class TestSqliteUserRepository:
    async def test_create_and_get_by_id(self, repo: SqliteUserRepository) -> None:
        qq = QqNumber("123456789")
        user = await repo.create(qq, game_id="player1")
        assert user.id == UserId(1)
        assert user.qq_number == qq

        fetched = await repo.get_by_id(user.id)
        assert fetched == user

    async def test_get_by_id_not_found(self, repo: SqliteUserRepository) -> None:
        assert await repo.get_by_id(UserId(999)) is None

    async def test_get_by_qq(self, repo: SqliteUserRepository) -> None:
        qq = QqNumber("987654321")
        await repo.create(qq, game_id="player2")

        fetched = await repo.get_by_qq(qq)
        assert fetched is not None
        assert fetched.qq_number == qq

    async def test_get_by_qq_not_found(self, repo: SqliteUserRepository) -> None:
        assert await repo.get_by_qq(QqNumber("000000")) is None

    async def test_create_duplicate_qq_raises(self, repo: SqliteUserRepository) -> None:
        qq = QqNumber("111222333")
        await repo.create(qq, game_id="p1")
        with pytest.raises(Exception):
            await repo.create(qq, game_id="p2")

    async def test_create_without_game_id(self, repo: SqliteUserRepository) -> None:
        user = await repo.create(QqNumber("555"), game_id=None)
        assert user.game_id is None

    async def test_roundtrip_timestamps(self, repo: SqliteUserRepository) -> None:
        user = await repo.create(QqNumber("666"), game_id=None)
        fetched = await repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.created_at.tzinfo is not None  # timezone-aware
```

- [ ] **Step 2: Run tests — expect import/attribute errors**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_user_repository.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SqliteUserRepository in repository.py**

```python
"""SQLite-backed repository implementations."""
from datetime import datetime, timezone

from aiosqlite import Connection

from pjsk_core.domain.users import QqNumber, User, UserId


class SqliteUserRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def get_by_id(self, user_id: UserId) -> User | None:
        rows = await self._conn.execute_fetchall(
            "SELECT id, qq_number, game_id, created_at, updated_at FROM users WHERE id = ?",
            (user_id.value,),
        )
        if not rows:
            return None
        return self._row_to_user(rows[0])

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        rows = await self._conn.execute_fetchall(
            "SELECT id, qq_number, game_id, created_at, updated_at FROM users WHERE qq_number = ?",
            (qq.value,),
        )
        if not rows:
            return None
        return self._row_to_user(rows[0])

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            "INSERT INTO users(qq_number, game_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (qq.value, game_id, now, now),
        )
        await self._conn.commit()
        uid = UserId(cursor.lastrowid)
        return await self.get_by_id(uid)  # type: ignore[return-value]

    def _row_to_user(self, row) -> User:
        return User(
            id=UserId(row["id"]),
            qq_number=QqNumber(row["qq_number"]),
            game_id=row["game_id"],
        )
```

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_user_repository.py -v`
Expected: 7 passed

- [ ] **Step 5: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core adapters tools tests`

- [ ] **Step 6: Commit**

Run: `git add adapters/database/repository.py tests/adapters/database/test_user_repository.py && git commit -m "feat: implement SQLite UserRepository"`

---

### Task 4: ChartRepository SQLite Implementation

**Files:**
- Modify: `adapters/database/repository.py` — add `SqliteChartRepository`
- Create: `tests/adapters/database/test_chart_repository.py`

**Interfaces:**
- Consumes: `ChartRepository` Protocol, `Difficulty`, `Chart` from `pjsk_core.domain.charts`
- Produces: `SqliteChartRepository`

- [ ] **Step 1: Write failing tests**

Create `tests/adapters/database/test_chart_repository.py`:

```python
"""SQLite ChartRepository contract tests."""
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteChartRepository
from pjsk_core.domain.charts import Chart, Difficulty


@pytest.fixture
async def repo(tmp_path: Path):
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteChartRepository(conn)
    finally:
        await conn.close()


async def _seed_song_and_chart(conn, song_id=1, difficulty="master",
                               official_level=30, constant="30.5", note_count=1200):
    await conn.execute(
        "INSERT INTO songs(id, title_ja) VALUES (?, ?)",
        (song_id, "Test Song"),
    )
    await conn.execute(
        "INSERT INTO charts(song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (song_id, difficulty, official_level, constant, note_count, "2026-07-12"),
    )
    await conn.commit()


class TestSqliteChartRepository:
    async def test_get_by_id(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn)
        chart = await repo.get_by_id(1)
        assert chart is not None
        assert chart.song_id == 1
        assert chart.difficulty == Difficulty.MASTER

    async def test_get_by_id_not_found(self, repo: SqliteChartRepository) -> None:
        assert await repo.get_by_id(999) is None

    async def test_find_by_song_and_difficulty(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=42)
        chart = await repo.find_by_song_and_difficulty("Test Song", Difficulty.MASTER)
        assert chart is not None
        assert chart.song_id == 42

    async def test_list_by_difficulty_level(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=1, difficulty="master", official_level=30)
        await _seed_song_and_chart(repo._conn, song_id=2, difficulty="master", official_level=31)
        await _seed_song_and_chart(repo._conn, song_id=3, difficulty="expert", official_level=30)
        songs = [
            (4, "Song4"), (5, "Song5"),
        ]
        for sid, title in songs:
            await repo._conn.execute(
                "INSERT INTO songs(id, title_ja) VALUES (?, ?)", (sid, title)
            )
        for sid, level, const in [(4, 30, "30.0"), (5, 31, "31.0")]:
            await repo._conn.execute(
                "INSERT INTO charts(song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
                "VALUES (?, 'master', ?, ?, 1000, '2026-07-12')",
                (sid, level, const),
            )
        await repo._conn.commit()

        level30 = await repo.list_by_difficulty_level(Difficulty.MASTER, 30)
        assert len(level30) == 2  # song_ids 1, 4

        level31 = await repo.list_by_difficulty_level(Difficulty.MASTER, 31)
        assert len(level31) == 2  # song_ids 2, 5

        level32 = await repo.list_by_difficulty_level(Difficulty.MASTER, 32)
        assert len(level32) == 0
```

- [ ] **Step 2: Run tests — expect attribute error (SqliteChartRepository not defined)**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_chart_repository.py -v`

- [ ] **Step 3: Implement SqliteChartRepository in repository.py**

Add to `adapters/database/repository.py`:

```python
from pjsk_core.domain.charts import Chart, Difficulty


class SqliteChartRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def get_by_id(self, chart_id: int) -> Chart | None:
        rows = await self._conn.execute_fetchall(
            "SELECT id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version "
            "FROM charts WHERE id = ?",
            (chart_id,),
        )
        if not rows:
            return None
        return self._row_to_chart(rows[0])

    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None:
        rows = await self._conn.execute_fetchall(
            "SELECT c.id, c.song_id, c.difficulty, c.official_level, c.community_constant, c.note_count, c.chart_data_version "
            "FROM charts c JOIN songs s ON s.id = c.song_id "
            "WHERE (s.title_ja = ? OR s.title_cn = ? OR s.title_en = ?) AND c.difficulty = ?",
            (song_title, song_title, song_title, difficulty.value),
        )
        if not rows:
            return None
        return self._row_to_chart(rows[0])

    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int
    ) -> list[Chart]:
        rows = await self._conn.execute_fetchall(
            "SELECT id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version "
            "FROM charts WHERE difficulty = ? AND official_level = ? "
            "ORDER BY community_constant DESC",
            (difficulty.value, official_level),
        )
        return [self._row_to_chart(r) for r in rows]

    def _row_to_chart(self, row) -> Chart:
        return Chart(
            id=row["id"],
            song_id=row["song_id"],
            difficulty=Difficulty(row["difficulty"]),
            official_level=row["official_level"],
            community_constant=row["community_constant"],
            note_count=row["note_count"],
            data_version=row["chart_data_version"],
        )
```

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_chart_repository.py -v`
Expected: 4 passed

- [ ] **Step 5: Full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v && .venv\Scripts\python -m ruff check . && .venv\Scripts\python -m mypy pjsk_core adapters tools tests`

- [ ] **Step 6: Commit**

Run: `git add adapters/database/repository.py tests/adapters/database/test_chart_repository.py && git commit -m "feat: implement SQLite ChartRepository"`

---

### Task 5: ScoreRepository SQLite Implementation

**Files:**
- Modify: `adapters/database/repository.py` — add `SqliteScoreRepository`
- Create: `tests/adapters/database/test_score_repository.py`

**Interfaces:**
- Consumes: `ScoreRepository` Protocol, `ScoreAttempt`, `ScoreStatus`, `Judgements` from `pjsk_core.domain.scores`
- Produces: `SqliteScoreRepository`

- [ ] **Step 1: Write failing tests**

Create `tests/adapters/database/test_score_repository.py`:

```python
"""SQLite ScoreRepository contract tests."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import (
    SqliteChartRepository,
    SqliteScoreRepository,
    SqliteUserRepository,
)
from pjsk_core.domain.charts import Chart
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, UserId


@pytest.fixture
async def repos(tmp_path: Path):
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    user_repo = SqliteUserRepository(conn)
    chart_repo = SqliteChartRepository(conn)
    score_repo = SqliteScoreRepository(conn)
    try:
        # Seed a user and a chart
        await user_repo.create(QqNumber("123456789"), game_id="player1")
        await conn.execute(
            "INSERT INTO songs(id, title_ja) VALUES (1, 'Test')"
        )
        await conn.execute(
            "INSERT INTO charts(id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
            "VALUES (1, 1, 'master', 30, '30.5', 1200, '2026-07-12')"
        )
        await conn.commit()
        yield score_repo, user_repo, chart_repo
    finally:
        await conn.close()


class TestSqliteScoreRepository:
    async def test_record_attempt_returns_with_id(self, repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
            accuracy=100.5,
            rating=3100.0,
            status=ScoreStatus.FC,
            image_sha256="abc123",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        saved = await score_repo.record_attempt(attempt)
        assert saved.id == 1
        assert saved.user_id == UserId(1)

    async def test_record_attempt_updates_personal_best(self, repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=800, great=200, good=0, bad=0, miss=0),
            accuracy=99.0, rating=2900.0, status=ScoreStatus.FC,
            image_sha256="def456", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        )
        await score_repo.record_attempt(attempt)

        best = await score_repo.get_personal_best(UserId(1), 1)
        assert best is not None
        assert best.rating == 2900.0

        # Better score replaces personal best
        better = ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=3200.0, status=ScoreStatus.AP,
            image_sha256="ghi789", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        )
        await score_repo.record_attempt(better)

        best = await score_repo.get_personal_best(UserId(1), 1)
        assert best.rating == 3200.0

    async def test_get_personal_best_not_found(self, repos) -> None:
        score_repo, _, _ = repos
        assert await score_repo.get_personal_best(UserId(1), 999) is None

    async def test_list_personal_bests(self, repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        await score_repo.record_attempt(ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=3200.0, status=ScoreStatus.AP,
            image_sha256="img1", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        ))
        bests = await score_repo.list_personal_bests(UserId(1))
        assert len(bests) == 1

    async def test_list_personal_bests_with_status_filter(self, repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        await score_repo.record_attempt(ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=3200.0, status=ScoreStatus.AP,
            image_sha256="img1", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        ))
        # FC-only filter should exclude AP
        fc_only = await score_repo.list_personal_bests(
            UserId(1), status_filter={ScoreStatus.FC}
        )
        assert len(fc_only) == 0
        # AP+FC filter should include AP
        both = await score_repo.list_personal_bests(
            UserId(1), status_filter={ScoreStatus.FC, ScoreStatus.AP}
        )
        assert len(both) == 1
```

- [ ] **Step 2: Run tests — expect attribute error**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_score_repository.py -v`

- [ ] **Step 3: Implement SqliteScoreRepository in repository.py**

Add to `adapters/database/repository.py`:

```python
from datetime import datetime, timezone

from aiosqlite import Connection

from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus


class SqliteScoreRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        now = attempt.created_at.isoformat()
        cursor = await self._conn.execute(
            """INSERT INTO score_attempts
               (user_id, chart_id, perfect, great, good, bad, miss,
                accuracy, rating, status, image_sha256, source_gateway,
                ocr_run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt.user_id.value, attempt.chart_id,
                attempt.judgements.perfect, attempt.judgements.great,
                attempt.judgements.good, attempt.judgements.bad,
                attempt.judgements.miss,
                attempt.accuracy, attempt.rating, attempt.status.value,
                attempt.image_sha256, attempt.source_gateway,
                attempt.ocr_run_id, now,
            ),
        )
        attempt_id = cursor.lastrowid

        # Update personal_best in same transaction
        best = await self._conn.execute_fetchall(
            "SELECT rating FROM personal_bests WHERE user_id = ? AND chart_id = ?",
            (attempt.user_id.value, attempt.chart_id),
        )
        if not best or attempt.rating >= best[0][0]:
            await self._conn.execute(
                """INSERT OR REPLACE INTO personal_bests
                   (user_id, chart_id, best_attempt_id, accuracy, rating, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt.user_id.value, attempt.chart_id, attempt_id,
                    attempt.accuracy, attempt.rating, attempt.status.value, now,
                ),
            )

        await self._conn.commit()

        return ScoreAttempt(
            id=attempt_id,
            user_id=attempt.user_id,
            chart_id=attempt.chart_id,
            judgements=attempt.judgements,
            accuracy=attempt.accuracy,
            rating=attempt.rating,
            status=attempt.status,
            image_sha256=attempt.image_sha256,
            source_gateway=attempt.source_gateway,
            ocr_run_id=attempt.ocr_run_id,
            created_at=attempt.created_at,
        )

    async def get_personal_best(
        self, user_id: UserId, chart_id: int
    ) -> ScoreAttempt | None:
        rows = await self._conn.execute_fetchall(
            """SELECT sa.* FROM score_attempts sa
               JOIN personal_bests pb ON pb.best_attempt_id = sa.id
               WHERE pb.user_id = ? AND pb.chart_id = ?""",
            (user_id.value, chart_id),
        )
        if not rows:
            return None
        return self._row_to_attempt(rows[0])

    async def list_personal_bests(
        self, user_id: UserId,
        status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        if status_filter:
            placeholders = ",".join("?" * len(status_filter))
            query = f"""
                SELECT sa.* FROM score_attempts sa
                JOIN personal_bests pb ON pb.best_attempt_id = sa.id
                WHERE pb.user_id = ? AND sa.status IN ({placeholders})
                ORDER BY sa.rating DESC
            """
            params = [user_id.value] + [s.value for s in status_filter]
        else:
            query = """
                SELECT sa.* FROM score_attempts sa
                JOIN personal_bests pb ON pb.best_attempt_id = sa.id
                WHERE pb.user_id = ?
                ORDER BY sa.rating DESC
            """
            params = [user_id.value]
        rows = await self._conn.execute_fetchall(query, params)
        return [self._row_to_attempt(r) for r in rows]

    def _row_to_attempt(self, row) -> ScoreAttempt:
        return ScoreAttempt(
            id=row["id"],
            user_id=UserId(row["user_id"]),
            chart_id=row["chart_id"],
            judgements=Judgements(
                perfect=row["perfect"], great=row["great"],
                good=row["good"], bad=row["bad"], miss=row["miss"],
            ),
            accuracy=row["accuracy"],
            rating=row["rating"],
            status=ScoreStatus(row["status"]),
            image_sha256=row["image_sha256"],
            source_gateway=row["source_gateway"],
            ocr_run_id=row["ocr_run_id"],
            created_at=datetime.fromisoformat(row["created_at"]).replace(
                tzinfo=timezone.utc
            ),
        )
```

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python -m pytest tests/adapters/database/test_score_repository.py -v`
Expected: 5 passed

- [ ] **Step 5: Full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v && .venv\Scripts\python -m ruff check . && .venv\Scripts\python -m mypy pjsk_core adapters tools tests`

- [ ] **Step 6: Commit**

Run: `git add adapters/database/repository.py tests/adapters/database/test_score_repository.py && git commit -m "feat: implement SQLite ScoreRepository with transactional personal_best"`

---

### Task 6: Chart Data Import Tool

**Files:**
- Create: `tools/import_chart_data.py`
- Create: `tests/tools/test_import_chart_data.py`

**Interfaces:**
- Consumes: `chart_data/*.json` files, `adapters.database` (migrator, connection, ChartRepository)
- Produces: `import_chart_data(db_path, data_dir) -> int` — returns count of charts imported

- [ ] **Step 1: Write failing tests**

Create `tests/tools/test_import_chart_data.py`:

```python
"""Tests for the chart data import tool."""
import json
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import SqliteChartRepository
from tools.import_chart_data import import_chart_data


def _write_chart_data(data_dir: Path, charts: list[dict]) -> None:
    data_file = data_dir / "pentatonic_master.json"
    data_file.write_text(
        json.dumps({"version": "2026-07-12", "source": "PENTATONIC", "charts": charts}),
        encoding="utf-8",
    )
    manifest = data_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"version": "2026-07-12", "files": {"pentatonic_master.json": "sha256:test"}}),
        encoding="utf-8",
    )


@pytest.fixture
async def chart_repo(tmp_path: Path):
    db = tmp_path / "test.db"
    data_dir = tmp_path / "chart_data"
    data_dir.mkdir()
    await run_migrations(db)
    conn = await get_connection(db)
    try:
        yield SqliteChartRepository(conn), db, data_dir
    finally:
        await conn.close()


class TestImportChartData:
    async def test_imports_valid_charts(self, chart_repo) -> None:
        repo, db, data_dir = chart_repo
        _write_chart_data(data_dir, [
            {
                "song_id": 1, "title_ja": "Test Song",
                "difficulty": "master", "official_level": 30,
                "community_constant": "30.5", "note_count": 1200,
            },
            {
                "song_id": 2, "title_ja": "Song 2",
                "difficulty": "master", "official_level": 31,
                "community_constant": "31.2", "note_count": 1300,
            },
        ])
        count = await import_chart_data(db, data_dir)
        assert count == 2

        chart = await repo.get_by_id(1)
        assert chart is not None
        assert chart.community_constant == "30.5"

    async def test_rejects_invalid_constant_format(self, chart_repo) -> None:
        _, db, data_dir = chart_repo
        _write_chart_data(data_dir, [
            {
                "song_id": 1, "title_ja": "Bad",
                "difficulty": "master", "official_level": 30,
                "community_constant": "abc", "note_count": 1000,
            },
        ])
        with pytest.raises(ValueError):
            await import_chart_data(db, data_dir)

    async def test_skips_invalid_difficulty(self, chart_repo) -> None:
        _, db, data_dir = chart_repo
        _write_chart_data(data_dir, [
            {
                "song_id": 1, "title_ja": "Test",
                "difficulty": "invalid_diff", "official_level": 30,
                "community_constant": "30.0", "note_count": 1000,
            },
        ])
        count = await import_chart_data(db, data_dir)
        assert count == 0

    async def test_idempotent_import(self, chart_repo) -> None:
        _, db, data_dir = chart_repo
        charts = [{
            "song_id": 1, "title_ja": "Test",
            "difficulty": "master", "official_level": 30,
            "community_constant": "30.5", "note_count": 1200,
        }]
        _write_chart_data(data_dir, charts)
        c1 = await import_chart_data(db, data_dir)
        c2 = await import_chart_data(db, data_dir)
        assert c1 == 1
        assert c2 == 0  # already imported, skip
```

- [ ] **Step 2: Run tests — expect import error**

Run: `.venv\Scripts\python -m pytest tests/tools/test_import_chart_data.py -v`

- [ ] **Step 3: Implement import_chart_data.py**

```python
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
```

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python -m pytest tests/tools/test_import_chart_data.py -v`
Expected: 4 passed

- [ ] **Step 5: Full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v && .venv\Scripts\python -m ruff check . && .venv\Scripts\python -m mypy pjsk_core adapters tools tests`

- [ ] **Step 6: Commit**

Run: `git add tools/import_chart_data.py tests/tools/test_import_chart_data.py && git commit -m "feat: add chart data import tool with validation"`

---

### Task 7: Final Verification

**Files:**
- No new files — verification only.

- [ ] **Step 1: Run complete test suite**

Run: `.venv\Scripts\python -m pytest -v`
Expected: all tests pass (~150+ total)

- [ ] **Step 2: Ruff + Mypy**

Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core adapters tools tests`

- [ ] **Step 3: Git status — confirm clean**

Run: `git status --short --branch`
Expected: clean working tree

- [ ] **Step 4: Commit (if any final cleanup)**

No commit needed unless ruff/mypy fixes required.

---

## Completion Gate

Phase 2 is complete when:
- chart_data JSON files exist with manifest
- Migration 001 creates all 6 tables on clean SQLite
- SqliteUserRepository, SqliteChartRepository, SqliteScoreRepository pass contract tests
- Chart data import tool validates and imports from JSON
- Full test suite passes
- Ruff + mypy strict zero errors
