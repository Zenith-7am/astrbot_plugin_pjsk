"""SQLite-backed repository implementations."""

from datetime import datetime, timezone

import sqlite3

from aiosqlite import Connection, Row

from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.song_matcher import SongCandidate
from pjsk_core.domain.users import QqNumber, User, UserId
from pjsk_core.ports.repositories import (
    AlreadyBoundError,
    DuplicateGameIdError,
    SongCatalog,
)


class SqliteChartRepository:
    """ChartRepository backed by an aiosqlite connection.

    Expects the songs and charts tables to have been created by
    the migration system. Returns domain Chart objects.

    Caches the SongCatalog across calls within the same schema version.
    The cache is invalidated when ``MAX(chart_data_version)`` changes,
    which is a cheap version-only query.  On cache miss the version and
    song rows are loaded in a single SELECT, giving a statement-level
    consistent snapshot regardless of journal_mode.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._catalog_cache: SongCatalog | None = None

    async def get_by_id(self, chart_id: int) -> Chart | None:
        rows = list(
            await self._conn.execute_fetchall(
                "SELECT id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version "
                "FROM charts WHERE id = ?",
                (chart_id,),
            )
        )
        if not rows:
            return None
        return self._row_to_chart(rows[0])

    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None:
        rows = list(
            await self._conn.execute_fetchall(
                "SELECT c.id, c.song_id, c.difficulty, c.official_level, c.community_constant, c.note_count, c.chart_data_version "
                "FROM charts c JOIN songs s ON s.id = c.song_id "
                "WHERE (s.title_ja = ? OR s.title_cn = ? OR s.title_en = ?) AND c.difficulty = ?",
                (song_title, song_title, song_title, difficulty.value),
            )
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
            "ORDER BY "
            "CAST(SUBSTR(community_constant, 1, INSTR(community_constant || '+', '+') - 1) AS REAL) DESC, "
            "CASE "
            "  WHEN community_constant LIKE '%+%' THEN 2 "
            "  WHEN community_constant LIKE '%-%' THEN 0 "
            "  ELSE 1 "
            "END DESC",
            (difficulty.value, official_level),
        )
        return [self._row_to_chart(r) for r in rows]

    async def get_song_catalog(self) -> SongCatalog:
        """Return the full list of songs as SongCandidates, including aliases.

        Uses an instance-level cache keyed on ``MAX(chart_data_version)``.
        A cheap version-only query avoids the full table scan when the
        catalog has not changed since the last call.

        On cache miss the version and song data are loaded in a single
        SELECT so they form a statement-level consistent snapshot — a
        concurrent chart-data import that commits between the version
        subquery and the song rows would be a separate statement and
        cannot interleave.
        """
        # Quick version check — no need to load everything if catalog is fresh
        version_rows = list(
            await self._conn.execute_fetchall(
                "SELECT MAX(chart_data_version) AS v FROM charts"
            )
        )
        current_version = (
            version_rows[0]["v"] if version_rows and version_rows[0]["v"] is not None
            else "unknown"
        )

        if (self._catalog_cache is not None
                and self._catalog_cache.version == current_version):
            return self._catalog_cache

        # Cache miss: single statement loads both version and songs —
        # SQLite statement-level consistency guarantees the version
        # matches the song rows regardless of journal_mode.
        rows = list(await self._conn.execute_fetchall(
            "SELECT s.id, s.title_ja, s.title_cn, s.title_en, s.aliases, "
            "(SELECT MAX(chart_data_version) FROM charts) AS version "
            "FROM songs s ORDER BY s.id"
        ))
        current_version = (
            rows[0]["version"] if rows and rows[0]["version"] is not None
            else "unknown"
        )

        candidates = tuple(
            SongCandidate(
                song_id=r["id"],
                title_ja=r["title_ja"],
                title_cn=r["title_cn"],
                title_en=r["title_en"],
                aliases=self._parse_aliases(r["aliases"]),
            )
            for r in rows
        )
        catalog = SongCatalog(version=current_version, candidates=candidates)
        self._catalog_cache = catalog
        return catalog

    async def get_by_song_and_difficulty(
        self, song_id: int, difficulty: Difficulty,
    ) -> Chart | None:
        rows = list(
            await self._conn.execute_fetchall(
                "SELECT id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version "
                "FROM charts WHERE song_id = ? AND difficulty = ?",
                (song_id, difficulty.value),
            )
        )
        if not rows:
            return None
        return self._row_to_chart(rows[0])

    @staticmethod
    def _parse_aliases(raw: str) -> tuple[str, ...]:
        """Parse JSON aliases column into a deduplicated tuple of non-empty strings.

        Returns an empty tuple on corrupt/missing data so callers never
        have to handle JSON errors."""
        import json
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return ()
            result = tuple(a for a in parsed if isinstance(a, str) and a.strip())
            # Dedup preserving order
            seen: set[str] = set()
            deduped: list[str] = []
            for a in result:
                if a not in seen:
                    deduped.append(a)
                    seen.add(a)
            return tuple(deduped)
        except (json.JSONDecodeError, TypeError):
            return ()

    def _row_to_chart(self, row: Row) -> Chart:
        return Chart(
            id=row["id"],
            song_id=row["song_id"],
            difficulty=Difficulty(row["difficulty"]),
            official_level=row["official_level"],
            community_constant=row["community_constant"],
            note_count=row["note_count"],
            data_version=row["chart_data_version"],
        )


class SqliteUserRepository:
    """UserRepository backed by an aiosqlite connection.

    Expects the users table to have been created by the migration system.
    Returns domain objects with timezone-aware datetime fields.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def get_by_id(self, user_id: UserId) -> User | None:
        cursor = await self._conn.execute(
            "SELECT id, qq_number, game_id, append_excluded, created_at, updated_at "
            "FROM users WHERE id = ?",
            (user_id.value,),
        )
        rows = list(await cursor.fetchall())
        if not rows:
            return None
        return self._row_to_user(rows[0])

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        cursor = await self._conn.execute(
            "SELECT id, qq_number, game_id, append_excluded, created_at, updated_at "
            "FROM users WHERE qq_number = ?",
            (qq.value,),
        )
        rows = list(await cursor.fetchall())
        if not rows:
            return None
        return self._row_to_user(rows[0])

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            "INSERT INTO users (qq_number, game_id, append_excluded, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (qq.value, game_id, now, now),
        )
        await self._conn.commit()
        lastrowid = cursor.lastrowid
        if lastrowid is None:
            raise RuntimeError("INSERT did not return a row id")
        uid = UserId(lastrowid)
        result = await self.get_by_id(uid)
        if result is None:
            raise RuntimeError(
                f"User row was inserted but could not be read back (id={uid})"
            )
        return result

    async def get_or_create(self, qq: QqNumber) -> User:
        """Return the existing user for *qq*, or create one with game_id=None.

        Uses ``INSERT OR IGNORE`` so two concurrent first-time callers
        both receive the same row — the first INSERT wins, the second
        is silently ignored, and both callers re-read the existing row.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (qq_number, game_id, append_excluded, created_at, updated_at) "
            "VALUES (?, NULL, 1, ?, ?)",
            (qq.value, now, now),
        )
        await self._conn.commit()
        result = await self.get_by_qq(qq)
        if result is None:
            raise RuntimeError(
                f"get_or_create failed for qq={qq.value}: "
                f"row not found after INSERT OR IGNORE"
            )
        return result

    async def bind_game_id(self, user_id: UserId, game_id: str) -> User:
        """Atomically bind a game_id to an existing user.

        Uses a conditional UPDATE (``WHERE game_id IS NULL``) so the
        check-and-set is a single SQL statement — no SELECT-then-write
        race.  The UNIQUE partial index from migration 005 catches the
        case where *another* user already owns this game_id.

        Returns
        -------
        User
            The updated user row.

        Raises
        ------
        AlreadyBoundError
            This user already has a (different) game_id bound.
        DuplicateGameIdError
            *Another* user already owns this game_id.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute("BEGIN")
        try:
            cursor = await self._conn.execute(
                "UPDATE users SET game_id = ?, updated_at = ? "
                "WHERE id = ? AND game_id IS NULL",
                (game_id, now, user_id.value),
            )
            if cursor.rowcount == 0:
                # User already has a game_id — check what it is
                row = await self._conn.execute_fetchall(
                    "SELECT game_id FROM users WHERE id = ?",
                    (user_id.value,),
                )
                rows = list(row)
                existing = rows[0]["game_id"] if rows else None
                if existing == game_id:
                    # Idempotent — same value, nothing to change
                    await self._conn.commit()
                    result = await self.get_by_id(user_id)
                    if result is None:
                        raise RuntimeError(f"User {user_id} disappeared")
                    return result
                # Different game_id → reject rebind
                await self._conn.rollback()
                raise AlreadyBoundError(
                    f"User {user_id.value} already bound to '{existing}'"
                )
            await self._conn.commit()
        except sqlite3.IntegrityError:
            await self._conn.rollback()
            raise DuplicateGameIdError(
                f"game_id '{game_id}' is already bound to another user"
            )
        except Exception:
            await self._conn.rollback()
            raise
        result = await self.get_by_id(user_id)
        if result is None:
            raise RuntimeError(
                f"User {user_id} disappeared after bind_game_id"
            )
        return result

    async def get_append_excluded(self, user_id: UserId) -> bool:
        cursor = await self._conn.execute(
            "SELECT append_excluded FROM users WHERE id = ?",
            (user_id.value,),
        )
        rows = list(await cursor.fetchall())
        if not rows:
            raise RuntimeError(f"User {user_id.value} not found")
        return bool(rows[0]["append_excluded"])

    async def set_append_excluded(self, user_id: UserId, excluded: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE users SET append_excluded = ?, updated_at = ? WHERE id = ?",
            (int(excluded), now, user_id.value),
        )
        await self._conn.commit()

    def _row_to_user(self, row: Row) -> User:
        return User(
            id=UserId(row["id"]),
            qq_number=QqNumber(row["qq_number"]),
            game_id=row["game_id"],
            append_excluded=bool(row["append_excluded"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class SqliteScoreRepository:
    """ScoreRepository backed by an aiosqlite connection.

    Expects the score_attempts and personal_bests tables to have been
    created by the migration system. Returns domain ScoreAttempt objects.
    record_attempt inserts the attempt and updates the personal best
    within a single transaction.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        await self._conn.execute("BEGIN")
        try:
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
            if attempt_id is None:
                raise RuntimeError("INSERT did not return a row id")

            # Atomic UPSERT — the WHERE clause prevents a lower rating
            # from overwriting a higher one, and the whole operation is
            # a single statement so there is no SELECT-then-write window.
            await self._conn.execute(
                """INSERT INTO personal_bests
                   (user_id, chart_id, best_attempt_id, accuracy,
                    rating, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, chart_id) DO UPDATE SET
                       best_attempt_id = excluded.best_attempt_id,
                       accuracy = excluded.accuracy,
                       rating = excluded.rating,
                       status = excluded.status,
                       updated_at = excluded.updated_at
                   WHERE excluded.rating >= personal_bests.rating""",
                (
                    attempt.user_id.value, attempt.chart_id, attempt_id,
                    attempt.accuracy, attempt.rating, attempt.status.value, now,
                ),
            )

            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            raise

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
        rows = list(
            await self._conn.execute_fetchall(
                """SELECT sa.* FROM score_attempts sa
                   JOIN personal_bests pb ON pb.best_attempt_id = sa.id
                   WHERE pb.user_id = ? AND pb.chart_id = ?""",
                (user_id.value, chart_id),
            )
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

    def _row_to_attempt(self, row: Row) -> ScoreAttempt:
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
