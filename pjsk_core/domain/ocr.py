"""Vision engine observation, validated results, consensus, and candidate ranking."""

from dataclasses import dataclass

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import Judgements


@dataclass(frozen=True)
class OcrObservation:
    """A single vision model's raw recognition result."""

    song_title: str
    difficulty: Difficulty
    displayed_level: int
    judgements: Judgements
    engine: str
    elapsed_ms: int


@dataclass(frozen=True)
class ValidatedObservation:
    """An OCR observation after song-name matching resolved a chart_id.

    Consensus should compare validated observations — not raw song_title
    strings — because two models may produce different spellings of the
    same song that both match to the same chart.
    """

    observation: OcrObservation
    matched_chart_id: int
    note_validated: bool


def validated_observations_agree(
    a: ValidatedObservation, b: ValidatedObservation,
) -> bool:
    """Two validated observations agree when they match the same chart
    and produce the same difficulty, level, and judgements."""
    return (
        a.matched_chart_id == b.matched_chart_id
        and a.observation.difficulty is b.observation.difficulty
        and a.observation.displayed_level == b.observation.displayed_level
        and a.observation.judgements == b.observation.judgements
    )


def observations_agree(a: OcrObservation, b: OcrObservation) -> bool:
    """Two raw observations agree on song_title, difficulty, level, and
    judgements.  Prefer :func:`validated_observations_agree` once song
    matching has resolved chart_ids — raw title comparison is fragile
    across engines with different OCR outputs."""
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


# ── Engine identity ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class EngineIdentity:
    """Stable identity for a vision engine instance.

    engine_id: globally unique instance identifier, e.g. "gemini-2.5-flash"
    provider:  vendor name, e.g. "google" — the consensus voting unit
    model:     model name, e.g. "gemini-2.5-flash"
    """
    engine_id: str
    provider: str
    model: str


# ── Vision engine error hierarchy ────────────────────────────────────────

class VisionEngineError(Exception):
    """Base for all vendor-engine failures."""

class VisionTimeoutError(VisionEngineError):
    """Request exceeded the allotted timeout."""

class VisionConnectionError(VisionEngineError):
    """Network-level connection failure."""

class VisionRateLimitError(VisionEngineError):
    """Vendor returned rate-limiting (HTTP 429)."""

class VisionServerError(VisionEngineError):
    """Vendor returned a server-side error (HTTP 5xx)."""

class VisionResponseError(VisionEngineError):
    """Vendor returned an unexpected response (HTTP 4xx ≠ 429, or invalid JSON)."""
