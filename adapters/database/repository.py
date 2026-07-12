"""SQLite-backed repository implementations."""

from datetime import datetime, timezone

from aiosqlite import Connection, Row

from pjsk_core.domain.charts import Chart, Difficulty
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
            "ORDER BY community_constant DESC",
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
