"""UserRateLimiter — simple in-memory per-user cooldown."""
from __future__ import annotations

import time

from pjsk_core.domain.users import UserId


class UserRateLimiter:
    """Prevent a single user from spamming OCR requests.

    Not a domain concept — this is a plugin-layer interaction guard.
    """

    def __init__(self, cooldown_seconds: float = 5.0) -> None:
        self._cooldown = cooldown_seconds
        self._marks: dict[int, float] = {}

    def check(self, user_id: UserId) -> bool:
        """Return True if the user is allowed to make a request."""
        last = self._marks.get(user_id.value)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._cooldown

    def mark(self, user_id: UserId) -> None:
        """Record that the user just made a request."""
        self._marks[user_id.value] = time.monotonic()
