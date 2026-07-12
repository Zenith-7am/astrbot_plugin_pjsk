"""Vision engine observation, consensus check, and candidate ranking."""

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


def observations_agree(a: OcrObservation, b: OcrObservation) -> bool:
    """Two observations agree when song_title, difficulty, level, and
    judgements match. Engine name and elapsed time are metadata — they
    do not affect consensus."""
    return (
        a.song_title == b.song_title
        and a.difficulty is b.difficulty
        and a.displayed_level == b.displayed_level
        and a.judgements == b.judgements
    )


@dataclass(frozen=True)
class Candidate:
    """A validated OCR result awaiting user confirmation.

    Used when multiple vision models disagree — each distinct
    observation becomes a numbered candidate ranked by quality.
    """

    observation: OcrObservation
    model_support: int
    note_validated: bool
    title_similarity: float
    note_distance: int
    matched_chart_id: int | None


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Sort candidates by quality, best first.

    Order (highest priority first):
    1. model_support descending (more models agree → stronger)
    2. note_validated (validated → before unvalidated)
    3. title_similarity descending
    4. note_distance ascending (closer to expected → better)
    5. matched_chart_id ascending, None last
    """
    return sorted(
        candidates,
        key=lambda c: (
            -c.model_support,
            not c.note_validated,
            -c.title_similarity,
            c.note_distance,
            c.matched_chart_id if c.matched_chart_id is not None else 999_999_999,
        ),
    )
