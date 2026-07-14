"""ToggleAppend use case — manage user's APPEND chart preference."""

from pjsk_core.domain.users import UserId
from pjsk_core.ports.repositories import UserRepository


class ToggleAppend:
    """Query and toggle the APPEND-exclusion preference.

    When excluded=True (default), APPEND charts are hidden from B20
    and difficulty rankings. Users who play APPEND charts are
    automatically opted-in via migration backfill.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def get(self, user_id: UserId) -> bool:
        """Return current append_excluded preference."""
        return await self._users.get_append_excluded(user_id)

    async def set(self, user_id: UserId, excluded: bool) -> None:
        """Update append_excluded preference."""
        await self._users.set_append_excluded(user_id, excluded)
