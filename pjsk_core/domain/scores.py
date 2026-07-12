"""Score status, judgement counts, and score attempt domain types."""

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
        if self.accuracy < 0:
            raise ValueError(f"accuracy must be non-negative, got: {self.accuracy}")
        if self.rating < 0:
            raise ValueError(f"rating must be non-negative, got: {self.rating}")
