"""B20 selection — pure function, no I/O, no repository knowledge."""

from dataclasses import dataclass

from pjsk_core.domain.scores import ScoreStatus


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


def select_b20(scores: list[RatedScore], limit: int = 20) -> list[RatedScore]:
    """Select top N FC/AP scores by rating, chart_id tiebreaker.

    CLEAR scores are excluded.  Fewer than `limit` results is valid.
    """
    eligible = [s for s in scores if s.status in (ScoreStatus.FC, ScoreStatus.AP)]
    eligible.sort(key=lambda s: (-s.rating, s.chart_id))
    return eligible[:limit]
