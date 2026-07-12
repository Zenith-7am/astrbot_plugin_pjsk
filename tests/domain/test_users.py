"""Tests for pjsk_core.domain.users — identity value objects."""

import pytest
from pjsk_core.domain.users import QqNumber, User, UserId


class TestQqNumber:
    def test_valid_qq_number(self) -> None:
        qq = QqNumber("123456789")
        assert qq.value == "123456789"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            QqNumber("")

    def test_non_digit_characters_raise(self) -> None:
        with pytest.raises(ValueError):
            QqNumber("abc123")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError):
            QqNumber("   ")

    def test_strips_and_validates(self) -> None:
        qq = QqNumber("  123456789  ")
        assert qq.value == "123456789"

    def test_equality(self) -> None:
        assert QqNumber("123") == QqNumber("123")
        assert QqNumber("123") != QqNumber("456")


class TestUserId:
    def test_valid_user_id(self) -> None:
        uid = UserId(1)
        assert uid.value == 1

    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            UserId(0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            UserId(-1)

    def test_equality(self) -> None:
        assert UserId(1) == UserId(1)
        assert UserId(1) != UserId(2)


class TestUser:
    def test_user_with_game_id(self) -> None:
        user = User(
            id=UserId(1),
            qq_number=QqNumber("123456789"),
            game_id="player123",
        )
        assert user.id == UserId(1)
        assert user.qq_number == QqNumber("123456789")
        assert user.game_id == "player123"

    def test_user_without_game_id(self) -> None:
        user = User(
            id=UserId(1),
            qq_number=QqNumber("123456789"),
            game_id=None,
        )
        assert user.game_id is None

    def test_empty_game_id_raises(self) -> None:
        with pytest.raises(ValueError):
            User(
                id=UserId(1),
                qq_number=QqNumber("123456789"),
                game_id="",
            )

    def test_frozen(self) -> None:
        user = User(id=UserId(1), qq_number=QqNumber("123"), game_id=None)
        with pytest.raises(Exception):
            user.game_id = "new"  # type: ignore[misc]
