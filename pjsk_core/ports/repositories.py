"""Repository ports for persistent storage of users, charts, and scores.

All methods return domain objects, never dicts or database rows.
"""

from typing import Protocol

from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId


class UserRepository(Protocol):
    """User identity persistence."""

    async def get_by_id(self, user_id: UserId) -> User | None: ...
    async def get_by_qq(self, qq: QqNumber) -> User | None: ...
    async def create(self, qq: QqNumber, game_id: str | None) -> User: ...


class ChartRepository(Protocol):
    """Chart and song metadata lookups."""

    async def get_by_id(self, chart_id: int) -> Chart | None: ...
    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None: ...
    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int
    ) -> list[Chart]: ...


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
