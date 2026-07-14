"""B20 selection — pure functions and result types, no I/O."""

from dataclasses import dataclass

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.player_class import PlayerClass
from pjsk_core.domain.scores import Judgements, ScoreStatus


@dataclass(frozen=True)
class RatedScore:
    """A personal-best score eligible for B20 ranking.

    Lightweight value object — ScoreAttempt carries too much context
    (user_id, image_sha256, created_at, etc.) that B20 doesn't need.
    """

    chart_id: int
    rating: float
    accuracy: float
    status: ScoreStatus


@dataclass(frozen=True)
class B20Entry:
    """One entry in a B20 result with resolved song/chart metadata."""

    rank: int
    song_id: int
    song_title: str
    difficulty: Difficulty
    official_level: int
    community_constant: str
    status: ScoreStatus
    accuracy: float
    rating: float
    judgements: Judgements


@dataclass(frozen=True)
class B20Result:
    """Complete B20 query result with computed SP and player class."""

    entries: tuple[B20Entry, ...]
    sp: float
    player_class: PlayerClass
    b20_avg: float
    fc_bonus: float
    ap_bonus: float
    append_excluded: bool
    chart_data_version: str


def select_b20(scores: list[RatedScore], limit: int = 20) -> list[RatedScore]:
    """Select top N FC/AP scores by rating, chart_id tiebreaker.

    CLEAR scores are excluded.  Fewer than `limit` results is valid.
    """
    eligible = [s for s in scores if s.status in (ScoreStatus.FC, ScoreStatus.AP)]
    eligible.sort(key=lambda s: (-s.rating, s.chart_id))
    return eligible[:limit]


def compute_sp(b20_entries: tuple[B20Entry, ...]) -> tuple[float, float, float, float]:
    """Compute SEKAI POWER from B20 entries.

    Returns (sp, b20_avg, fc_bonus, ap_bonus).
    fc_bonus and ap_bonus are reserved (always 0.0 for now).
    """
    if not b20_entries:
        return (0.0, 0.0, 0.0, 0.0)
    b20_avg = sum(e.rating for e in b20_entries) / len(b20_entries)
    # Full FC/AP bonuses reserved for future implementation
    fc_bonus = 0.0
    ap_bonus = 0.0
    sp = b20_avg + fc_bonus + ap_bonus
    return (round(sp, 6), round(b20_avg, 6), fc_bonus, ap_bonus)
