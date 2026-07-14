"""Tests for ToggleAppend application use case."""

from pjsk_core.application.toggle_append import ToggleAppend
from pjsk_core.domain.users import QqNumber, User, UserId


class FakeUserRepository:
    def __init__(self, append_excluded: bool = True) -> None:
        self._append_excluded = append_excluded
        self._set_calls: list[tuple[UserId, bool]] = []

    async def get_append_excluded(self, user_id: UserId) -> bool:
        return self._append_excluded

    async def set_append_excluded(self, user_id: UserId, excluded: bool) -> None:
        self._set_calls.append((user_id, excluded))
        self._append_excluded = excluded

    # Unused
    async def get_by_id(self, user_id: UserId) -> User | None:
        raise NotImplementedError

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        raise NotImplementedError

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        raise NotImplementedError

    async def get_or_create(self, qq: QqNumber) -> User:
        raise NotImplementedError

    async def bind_game_id(self, user_id: UserId, game_id: str) -> User:
        raise NotImplementedError


class TestToggleAppend:
    async def test_get_returns_default_true(self) -> None:
        """Default: new user has append_excluded=True."""
        toggle = ToggleAppend(FakeUserRepository(append_excluded=True))
        result = await toggle.get(UserId(1))
        assert result is True

    async def test_set_toggles_to_false(self) -> None:
        """Toggle to excluded=False."""
        repo = FakeUserRepository(append_excluded=True)
        toggle = ToggleAppend(repo)
        await toggle.set(UserId(1), False)
        result = await toggle.get(UserId(1))
        assert result is False

    async def test_set_toggles_back_to_true(self) -> None:
        """Toggle back to excluded=True."""
        repo = FakeUserRepository(append_excluded=False)
        toggle = ToggleAppend(repo)
        await toggle.set(UserId(1), True)
        result = await toggle.get(UserId(1))
        assert result is True

    async def test_set_passes_correct_user_id(self) -> None:
        """set() delegates to UserRepository with the right user_id."""
        repo = FakeUserRepository()
        toggle = ToggleAppend(repo)
        await toggle.set(UserId(42), False)
        assert repo._set_calls == [(UserId(42), False)]
