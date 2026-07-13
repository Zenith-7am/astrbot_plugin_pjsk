"""Tests for UserRateLimiter."""
import time

from plugin.rate_limiter import UserRateLimiter
from pjsk_core.domain.users import UserId


class TestUserRateLimiter:
    def test_first_check_allowed(self) -> None:
        rl = UserRateLimiter()
        assert rl.check(UserId(1)) is True

    def test_mark_then_check_denied(self) -> None:
        rl = UserRateLimiter(cooldown_seconds=60.0)
        rl.mark(UserId(1))
        assert rl.check(UserId(1)) is False

    def test_different_users_independent(self) -> None:
        rl = UserRateLimiter(cooldown_seconds=60.0)
        rl.mark(UserId(1))
        assert rl.check(UserId(2)) is True

    def test_cooled_down_after_cooldown(self) -> None:
        rl = UserRateLimiter(cooldown_seconds=0.0)
        rl.mark(UserId(1))
        # cooldown_seconds=0 means check uses monotonic now
        # Small sleep ensures monotonic advances
        time.sleep(0.01)
        assert rl.check(UserId(1)) is True
