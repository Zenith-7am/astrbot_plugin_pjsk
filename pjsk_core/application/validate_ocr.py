"""ValidationPipeline — application-layer validation of OCR observations.

Takes a raw OcrObservation from VisionRace, matches song_title against the
database via SongMatcher, validates difficulty/note_count/level, and produces
a ValidatedObservation with STRONG / CANDIDATE / REJECTED status.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pjsk_core.domain.charts import Chart
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.song_matcher import (
    SongMatch,
    SongMatchMethod,
    match_song,
)
from pjsk_core.ports.repositories import ChartRepository

MAX_VALIDATION_CANDIDATES = 5
"""Maximum number of SongMatch candidates to validate from the matcher."""

STRONG_FUZZY_SCORE = 0.82
"""Fuzzy match score threshold for STRONG status."""


class ValidationStatus(Enum):
    """Result of validating an OCR observation against known chart data."""

    STRONG = "strong"
    CANDIDATE = "candidate"
    REJECTED = "rejected"


_STATUS_SORT = {
    ValidationStatus.STRONG: 0,
    ValidationStatus.CANDIDATE: 1,
    ValidationStatus.REJECTED: 2,
}
"""Sort priority for candidate ordering — STRONG before CANDIDATE before REJECTED."""


@dataclass(frozen=True)
class ValidatedCandidate:
    """Validation result for a single song-match candidate."""

    song_match: SongMatch
    chart: Chart | None
    note_distance: int | None
    note_validated: bool
    level_validated: bool
    status: ValidationStatus


@dataclass(frozen=True)
class ValidatedObservation:
    """Full validation result for one OCR observation across top-N matches."""

    observation: OcrObservation
    primary: ValidatedCandidate | None
    candidates: tuple[ValidatedCandidate, ...]
    status: ValidationStatus


class ValidationPipeline:
    """Validates an OcrObservation against the chart database.

    Steps:
        1. Fetch SongCatalog from ChartRepository.
        2. Run match_song() against catalog candidates (max N).
        3. For each candidate, look up the chart and validate note/level.
        4. Sort candidates by quality; pick primary.
        5. Derive overall ValidationStatus.
    """

    def __init__(self, charts: ChartRepository) -> None:
        self._charts = charts

    async def validate(
        self, observation: OcrObservation,
    ) -> ValidatedObservation:
        catalog = await self._charts.get_song_catalog()
        song_matches = match_song(
            observation.song_title, catalog.candidates,
        )[:MAX_VALIDATION_CANDIDATES]

        if not song_matches:
            return ValidatedObservation(
                observation=observation,
                primary=None,
                candidates=(),
                status=ValidationStatus.REJECTED,
            )

        validated_candidates: list[ValidatedCandidate] = []
        for match in song_matches:
            chart = await self._charts.get_by_song_and_difficulty(
                match.song_id, observation.difficulty,
            )
            vc = self._assess(match, chart, observation)
            validated_candidates.append(vc)

        validated_candidates.sort(
            key=lambda vc: (
                _STATUS_SORT[vc.status],
                not vc.note_validated,
                vc.chart is None,
                -(vc.song_match.score),
                vc.note_distance if vc.note_distance is not None else 9999,
                vc.song_match.song_id,
            ),
        )
        return ValidatedObservation(
            observation=observation,
            primary=validated_candidates[0] if validated_candidates else None,
            candidates=tuple(validated_candidates),
            status=validated_candidates[0].status if validated_candidates
                   else ValidationStatus.REJECTED,
        )

    @staticmethod
    def _assess(
        match: SongMatch, chart: Chart | None,
        observation: OcrObservation,
    ) -> ValidatedCandidate:
        """Assess a single match/chart pair against the observation.

        Returns a ValidatedCandidate with validation flags set.
        """
        if chart is None:
            return ValidatedCandidate(
                song_match=match, chart=None,
                note_distance=None, note_validated=False,
                level_validated=False, status=ValidationStatus.CANDIDATE,
            )

        total = (observation.judgements.perfect + observation.judgements.great
                 + observation.judgements.good + observation.judgements.bad
                 + observation.judgements.miss)
        if total == 0:
            return ValidatedCandidate(
                song_match=match, chart=chart,
                note_distance=None, note_validated=False,
                level_validated=False, status=ValidationStatus.REJECTED,
            )

        note_distance = abs(total - chart.note_count)
        note_ok = note_distance <= 1
        level_ok = observation.displayed_level == chart.official_level

        match_is_strong = (
            match.method in (SongMatchMethod.EXACT, SongMatchMethod.REGION)
            or (match.method == SongMatchMethod.FUZZY
                and match.score >= STRONG_FUZZY_SCORE)
        )

        if note_ok and level_ok and match_is_strong:
            status = ValidationStatus.STRONG
        else:
            status = ValidationStatus.CANDIDATE

        return ValidatedCandidate(
            song_match=match, chart=chart,
            note_distance=note_distance, note_validated=note_ok,
            level_validated=level_ok, status=status,
        )
