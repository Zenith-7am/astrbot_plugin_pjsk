"""User identity value objects — QQ number, user ID, and user entity."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QqNumber:
    """A validated QQ number as a digit-only string."""

    value: str

    def __post_init__(self) -> None:
        stripped = self.value.strip()
        if not stripped:
            raise ValueError("QQ number must not be empty")
        if not stripped.isdigit():
            raise ValueError(
                f"QQ number must contain only digits, got: {self.value!r}"
            )
        if stripped != self.value:
            object.__setattr__(self, "value", stripped)


@dataclass(frozen=True)
class UserId:
    """Internal user primary key."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"User ID must be non-negative, got: {self.value}")


@dataclass(frozen=True)
class User:
    """A registered user with QQ identity and optional game binding."""

    id: UserId
    qq_number: QqNumber
    game_id: str | None

    def __post_init__(self) -> None:
        if self.game_id is not None and self.game_id == "":
            raise ValueError("game_id must be None or a non-empty string")
