"""RegisterUser — create an internal user record from a QQ identity."""
from __future__ import annotations

import logging

from pjsk_core.domain.users import QqNumber, User
from pjsk_core.ports.repositories import UserRepository

_logger = logging.getLogger(__name__)


class RegisterUser:
    """Register the caller's QQ number as an internal user.

    This is the first user-visible action before any score-related feature.
    It creates a ``users`` row keyed by QQ number (from the OneBot event),
    with no game-ID binding.

    ``execute()`` returns ``(user, is_new)`` so the gateway can give
    distinct replies for first-time vs. returning users.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, qq: QqNumber) -> tuple[User, bool]:
        """Ensure a user record exists for *qq*.

        Returns
        -------
        (User, is_new)
            *is_new* is ``True`` when the row was just created,
            ``False`` when it already existed.
        """
        existing = await self._users.get_by_qq(qq)
        if existing is not None:
            return (existing, False)

        user = await self._users.get_or_create(qq)
        # In a rare race (two concurrent first-time calls), get_or_create
        # returns the row created by the other caller — we still report
        # "new".  This is harmless: the UNIQUE constraint guarantees at
        # most one row, and the user sees a duplicate success message at
        # worst.
        return (user, True)
