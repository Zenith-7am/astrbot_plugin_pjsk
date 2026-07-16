"""Connection factory and Unit of Work for SQLite transaction boundaries."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import aiosqlite


async def open_readonly_sqlite(path: str | Path) -> aiosqlite.Connection:
    """Open a read-only SQLite connection.

    Read-only is enforced at the database engine level (``mode=ro`` in
    the URI), not just by application discipline.  Any INSERT / UPDATE /
    DELETE on this connection will fail with ``SQLITE_READONLY``.
    """
    quoted = quote(str(path))
    conn = await aiosqlite.connect(f"file:{quoted}?mode=ro", uri=True)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA query_only = ON")
    return conn


class ConnectionFactory:
    """Creates aiosqlite connections sharing a single WAL-mode database."""

    def __init__(self, db_path: str | Path, *, readonly: bool = False) -> None:
        self._db_path = Path(db_path)
        self._readonly = readonly

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def connect(self) -> aiosqlite.Connection:
        """Create a new connection. Caller is responsible for closing it."""
        if self._readonly:
            return await open_readonly_sqlite(self._db_path)
        from adapters.database.connection import get_connection
        return await get_connection(self._db_path)


class UnitOfWork:
    """Transaction boundary sharing a single connection across repositories.

    Usage::

        factory = ConnectionFactory(db_path)
        async with UnitOfWork(factory) as uow:
            conn = uow.connection
            # pass conn to repositories
            # COMMIT on success, ROLLBACK on exception
    """

    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory
        self._conn: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        """The active connection. Raises RuntimeError if not entered."""
        if self._conn is None:
            raise RuntimeError("UnitOfWork not entered — use 'async with'")
        return self._conn

    async def __aenter__(self) -> UnitOfWork:
        self._conn = await self._factory.connect()
        await self._conn.execute("BEGIN")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        if self._conn is None:
            return False
        try:
            if exc_type is None:
                await self._conn.commit()
            else:
                await self._conn.rollback()
        finally:
            await self._conn.close()
            self._conn = None
        return False
