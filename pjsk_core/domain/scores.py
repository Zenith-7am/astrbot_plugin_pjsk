"""Score status, judgement counts, score attempt domain types, and pure rules."""

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pjsk_core.domain.users import UserId


class ScoreStatus(Enum):
    """Play result classification."""

    AP = "ap"
    FC = "fc"
    CLEAR = "clear"


@dataclass(frozen=True)
class Judgements:
    """Counts for each judgement tier in a single play."""

    perfect: int
    great: int
    good: int
    bad: int
    miss: int

    def __post_init__(self) -> None:
        for field_name in ("perfect", "great", "good", "bad", "miss"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(
                    f"{field_name} must be non-negative, got: {value}"
                )


@dataclass(frozen=True)
class ScoreAttempt:
    """A single confirmed score submission.

    id is None before database insert; assigned by the repository.
    """

    id: int | None
    user_id: UserId
    chart_id: int
    judgements: Judgements
    accuracy: float
    rating: float
    status: ScoreStatus
    image_sha256: str
    source_gateway: str
    ocr_run_id: int | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if not math.isfinite(self.accuracy):
            raise ValueError("accuracy must be finite")
        if not (0.0 <= self.accuracy <= 101.0):
            raise ValueError(
                f"accuracy must be between 0 and 101, got: {self.accuracy}"
            )
        if not math.isfinite(self.rating):
            raise ValueError("rating must be finite")
        if self.rating < 0:
            raise ValueError(f"rating must be non-negative, got: {self.rating}")


# ── Pure functions (no I/O, no framework imports) ──────────────────────


def calculate_accuracy(j: Judgements) -> float:
    """Accuracy = (P + G×0.75 + Good×0.5) / N × 101.

    AP (no non-perfect judgements with at least one perfect) is forced
    to exactly 101.0%.  Results are capped at 101.0%.
    """
    total = j.perfect + j.great + j.good + j.bad + j.miss
    if total == 0:
        return 0.0
    raw = (j.perfect + j.great * 0.75 + j.good * 0.5) / total * 101
    if j.great == 0 and j.good == 0 and j.bad == 0 and j.miss == 0 and j.perfect > 0:
        return 101.0
    return min(101.0, raw)


def classify_status(j: Judgements) -> ScoreStatus:
    """Classify a play as AP, FC, or CLEAR from its judgement counts.

    AP  : perfect > 0, great = good = bad = miss = 0.
    FC  : good = bad = miss = 0 (GREAT keeps combo, GOOD breaks it).
    CLEAR: anything else, including all-zero.
    """
    total = j.perfect + j.great + j.good + j.bad + j.miss
    if total == 0:
        return ScoreStatus.CLEAR
    if j.great == 0 and j.good == 0 and j.bad == 0 and j.miss == 0 and j.perfect > 0:
        return ScoreStatus.AP
    if j.good == 0 and j.bad == 0 and j.miss == 0:
        return ScoreStatus.FC
    return ScoreStatus.CLEAR
