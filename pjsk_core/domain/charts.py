"""Chart and difficulty domain types for Project SEKAI."""

from dataclasses import dataclass
from enum import Enum


class Difficulty(Enum):
    """PJSK difficulty levels."""

    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    EXPERT = "expert"
    MASTER = "master"
    APPEND = "append"


@dataclass(frozen=True)
class Chart:
    """A playable chart (song + difficulty combination).

    community_constant is the community-researched precise difficulty
    rating (e.g. "31.2", "32.5+", "30.1-"). Parsing of suffixes is
    deferred to the rating domain (Task 3).
    """

    id: int
    song_id: int
    difficulty: Difficulty
    official_level: int
    community_constant: str
    note_count: int
    data_version: str

    def __post_init__(self) -> None:
        if self.official_level <= 0:
            raise ValueError(
                f"official_level must be positive, got: {self.official_level}"
            )
        if self.note_count <= 0:
            raise ValueError(
                f"note_count must be positive, got: {self.note_count}"
            )
