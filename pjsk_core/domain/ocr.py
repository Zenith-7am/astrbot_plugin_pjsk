"""Vision engine observation — raw OCR result before validation."""

from dataclasses import dataclass

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import Judgements


@dataclass(frozen=True)
class OcrObservation:
    """A single vision model's recognition result."""

    song_title: str
    difficulty: Difficulty
    displayed_level: int
    judgements: Judgements
    engine: str
    elapsed_ms: int
