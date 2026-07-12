"""SQLite-backed repository implementations."""

from datetime import datetime, timezone

from aiosqlite import Connection, Row

from pjsk_core.domain.users import QqNumber, User, UserId


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
        assert result is not None
        return result

    def _row_to_user(self, row: Row) -> User:
        return User(
            id=UserId(row["id"]),
            qq_number=QqNumber(row["qq_number"]),
            game_id=row["game_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
