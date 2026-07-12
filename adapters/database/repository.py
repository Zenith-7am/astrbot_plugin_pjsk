"""SQLite-backed repository implementations."""

from datetime import datetime, timezone

from aiosqlite import Connection, Row

from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId


class SqliteChartRepository:
    """ChartRepository backed by an aiosqlite connection.

    Expects the songs and charts tables to have been created by
    the migration system. Returns domain Chart objects.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

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
            "SELECT id, qq_number, game_id, created_at, updated_at "
            "FROM users WHERE id = ?",
            (user_id.value,),
        )
        rows = list(await cursor.fetchall())
        if not rows:
            return None
        return self._row_to_user(rows[0])

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        cursor = await self._conn.execute(
            "SELECT id, qq_number, game_id, created_at, updated_at "
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
            "INSERT INTO users (qq_number, game_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
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

    def _row_to_user(self, row: Row) -> User:
        return User(
            id=UserId(row["id"]),
            qq_number=QqNumber(row["qq_number"]),
            game_id=row["game_id"],
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

            # Update personal_best in same transaction
            best = list(
                await self._conn.execute_fetchall(
                    "SELECT rating FROM personal_bests WHERE user_id = ? AND chart_id = ?",
                    (attempt.user_id.value, attempt.chart_id),
                )
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
