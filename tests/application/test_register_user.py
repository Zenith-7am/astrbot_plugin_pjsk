"""Tests for RegisterUser use case."""
from pjsk_core.application.register_user import RegisterUser
from pjsk_core.domain.users import QqNumber, User, UserId


# ── Fake Repository ──────────────────────────────────────────────────────────


class _FakeUserRepository:
    """In-memory UserRepository for RegisterUser tests."""

    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._by_qq: dict[str, User] = {}
        self._next_id = 1

    async def get_by_id(self, user_id: UserId) -> User | None:
        return self._users.get(user_id.value)

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        return self._by_qq.get(qq.value)

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        uid = UserId(self._next_id)
        self._next_id += 1
        user = User(id=uid, qq_number=qq, game_id=game_id)
        self._users[uid.value] = user
        self._by_qq[qq.value] = user
        return user

    async def get_or_create(self, qq: QqNumber) -> User:
        existing = self._by_qq.get(qq.value)
        if existing is not None:
            return existing
        return await self.create(qq, None)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRegisterUser:
    async def test_first_register_returns_new(self) -> None:
        repo = _FakeUserRepository()
        uc = RegisterUser(repo)
        qq = QqNumber("12345678")
        user, is_new = await uc.execute(qq)
        assert is_new is True
        assert user.qq_number == qq
        assert user.id.value == 1

    async def test_second_register_returns_existing(self) -> None:
        repo = _FakeUserRepository()
        uc = RegisterUser(repo)
        qq = QqNumber("12345678")
        await uc.execute(qq)  # first
        user, is_new = await uc.execute(qq)  # second
        assert is_new is False
        assert user.qq_number == qq

    async def test_register_is_idempotent(self) -> None:
        repo = _FakeUserRepository()
        uc = RegisterUser(repo)
        qq = QqNumber("12345678")
        user1, _ = await uc.execute(qq)
        user2, _ = await uc.execute(qq)
        user3, _ = await uc.execute(qq)
        assert user1.id == user2.id == user3.id
        assert len(repo._users) == 1

    async def test_different_qqs_get_different_users(self) -> None:
        repo = _FakeUserRepository()
        uc = RegisterUser(repo)
        qq1 = QqNumber("11111111")
        qq2 = QqNumber("22222222")
        u1, _ = await uc.execute(qq1)
        u2, _ = await uc.execute(qq2)
        assert u1.id != u2.id
        assert len(repo._users) == 2
