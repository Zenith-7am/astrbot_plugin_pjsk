"""Difficulty ranking domain types — pure data classes, no I/O."""

from dataclasses import dataclass

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import ScoreAttempt, ScoreStatus


@dataclass(frozen=True)
class DifficultyRankEntry:
    """One entry in a difficulty ranking — a chart with optional personal best."""

    song_id: int
    song_title: str
    chart_id: int
    community_constant: str
    const_tag: str  # "+" / "-" / ""
    official_level: int
    note_count: int
    personal_best: ScoreAttempt | None  # None = unplayed
    is_played: bool

    @property
    def status(self) -> ScoreStatus | None:
        """Shortcut to personal best status, if played."""
        return self.personal_best.status if self.personal_best else None

    @property
    def accuracy(self) -> float | None:
        """Shortcut to personal best accuracy, if played."""
        return self.personal_best.accuracy if self.personal_best else None

    @property
    def rating(self) -> float | None:
        """Shortcut to personal best rating, if played."""
        return self.personal_best.rating if self.personal_best else None


@dataclass(frozen=True)
class DifficultyRanking:
    """Complete difficulty ranking for one (difficulty, official_level) pair."""

    difficulty: Difficulty
    official_level: int
    mode: str  # "global" or "personal"
    entries: tuple[DifficultyRankEntry, ...]

    @property
    def played_count(self) -> int:
        return sum(1 for e in self.entries if e.is_played)

    @property
    def total_count(self) -> int:
        return len(self.entries)


def _const_sort_key(community_constant: str) -> tuple[float, int]:
    """Sort key: higher constant first. Same value: + > none > -.

    Examples:
        32.5+ → (32.55, 2)
        32.5  → (32.5, 1)
        32.5- → (32.45, 0)
    """
    base = community_constant.rstrip("+-")
    tag = community_constant[len(base):] if len(base) < len(community_constant) else ""

    # Determine the numeric base
    if base.endswith(".5+"):
        # "32.5+" → 32.55
        numeric = float(base.replace(".5+", "")) + 0.55
        tag_order = 2
    elif base.endswith(".5"):
        # "32.5" → 32.5
        numeric = float(base)
        tag_order = 1
    else:
        numeric = float(base) if base else 0.0
        tag_order = 1

    if tag == "+":
        tag_order = 2
    elif tag == "-":
        tag_order = 0

    # Negative for descending sort
    return (-numeric, -tag_order)


def sort_charts_by_constant(
    entries: list[DifficultyRankEntry],
) -> list[DifficultyRankEntry]:
    """Sort entries by community_constant DESC, then song_id ASC."""
    return sorted(
        entries,
        key=lambda e: (_const_sort_key(e.community_constant), e.song_id),
    )
