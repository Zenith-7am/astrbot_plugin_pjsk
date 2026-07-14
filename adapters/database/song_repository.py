"""SQLite-backed SongRepository adapter."""

from aiosqlite import Connection, Row

from pjsk_core.domain.song import Song


class SqliteSongRepository:
    """SongRepository backed by an aiosqlite connection.

    Expects the songs table to have been created by the migration system.
    Returns domain Song objects.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def get_by_id(self, song_id: int) -> Song | None:
        rows = list(
            await self._conn.execute_fetchall(
                "SELECT id, title_ja, title_cn, title_en, aliases "
                "FROM songs WHERE id = ?",
                (song_id,),
            )
        )
        if not rows:
            return None
        return self._row_to_song(rows[0])

    async def get_all(self) -> list[Song]:
        rows = await self._conn.execute_fetchall(
            "SELECT id, title_ja, title_cn, title_en, aliases "
            "FROM songs ORDER BY id"
        )
        return [self._row_to_song(r) for r in rows]

    @staticmethod
    def _row_to_song(row: Row) -> Song:
        return Song(
            id=row["id"],
            title_ja=row["title_ja"],
            title_cn=row["title_cn"],
            title_en=row["title_en"],
            aliases=row["aliases"],
        )
