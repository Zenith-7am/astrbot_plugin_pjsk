"""Repository ports for persistent storage of users, charts, and scores.

All methods return domain objects, never dicts or database rows.
"""

from dataclasses import dataclass
from typing import Protocol

from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import ScoreAttempt, ScoreStatus
from pjsk_core.domain.song_matcher import SongCandidate
from pjsk_core.domain.users import QqNumber, User, UserId


@dataclass(frozen=True)
class SongCatalog:
    """Versioned catalog of all songs available for OCR matching."""

    version: str
    candidates: tuple[SongCandidate, ...]


class BindError(Exception):
    """Raised when a bind operation cannot complete."""


class DuplicateGameIdError(BindError):
    """The game_id is already bound to a different QQ account."""


class AlreadyBoundError(BindError):
    """The user already has a different game_id bound (re-binding not yet supported)."""


class UserRepository(Protocol):
    """User identity persistence."""

    async def get_by_id(self, user_id: UserId) -> User | None: ...
    async def get_by_qq(self, qq: QqNumber) -> User | None: ...
    async def create(self, qq: QqNumber, game_id: str | None) -> User: ...
    async def bind_game_id(self, user_id: UserId, game_id: str) -> User: ...
    """Atomically bind a game_id to an existing user.

    Raises:
        DuplicateGameIdError: game_id already belongs to another user.
    """


class ChartRepository(Protocol):
    """Chart and song metadata lookups."""

    async def get_by_id(self, chart_id: int) -> Chart | None: ...
    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None: ...
    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int
    ) -> list[Chart]: ...

    async def get_song_catalog(self) -> SongCatalog: ...

    async def get_by_song_and_difficulty(
        self, song_id: int, difficulty: Difficulty,
    ) -> Chart | None: ...


class ScoreRepository(Protocol):
    """Score persistence and personal best tracking.

    record_attempt inserts the attempt and updates the personal best
    within a single transaction.
    """

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt: ...
    async def get_personal_best(
        self, user_id: UserId, chart_id: int
    ) -> ScoreAttempt | None: ...
    async def list_personal_bests(
        self, user_id: UserId, status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]: ...
