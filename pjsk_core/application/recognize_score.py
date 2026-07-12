"""RecognizeScore use case — coordinate vision race, record on consensus/degraded."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from dataclasses import dataclass

from pjsk_core.application.vision_race import (
    EngineResultStatus,
    VisionRace,
    VisionRaceDecision,
    VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate,
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.domain.ocr import (
    Candidate,
    EngineIdentity,
    OcrObservation,
    rank_candidates,
)
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import (
    Judgements,
    ScoreAttempt,
    calculate_accuracy,
    classify_status,
)
from pjsk_core.domain.rating import calculate_rating
from pjsk_core.domain.users import UserId
from pjsk_core.ports.repositories import ScoreRepository


@dataclass(frozen=True)
class RecognizeResult:
    """Result of a score recognition attempt."""

    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]
    score_attempt: ScoreAttempt | None


class RecognizeScore:
    """Top-level use case: run vision race, construct score, persist.

    Takes a VisionRace orchestrator and a ScoreRepository, then:
    - On CONSENSUS / DEGRADED_SINGLE: constructs a ScoreAttempt from the
      validated observation, records it via ScoreRepository.
    - On DISAGREEMENT: returns candidates for user confirmation (Phase 3b).
    - On ALL_FAILED / NO_AVAILABLE_ENGINES: returns no score.
    - On GLOBAL_TIMEOUT: adopts single STRONG result as degraded; else
      returns error.
    """

    def __init__(
        self,
        race: VisionRace,
        scores: ScoreRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._race = race
        self._scores = scores
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def recognize(
        self,
        user_id: UserId,
        image: bytes,
        *,
        source_gateway: str,
    ) -> RecognizeResult:
        """Run vision race, record score if consensus or degraded-single."""
        image_sha256 = hashlib.sha256(image).hexdigest()
        outcome = await self._race.run(image)

        if outcome.decision in (
            VisionRaceDecision.CONSENSUS,
            VisionRaceDecision.DEGRADED_SINGLE,
        ):
            selected = outcome.selected
            if selected is None or selected.primary is None:
                return RecognizeResult(
                    outcome=outcome, validated=selected,
                    candidates_for_user=(), score_attempt=None,
                )
            attempt = await self._record(
                selected, user_id, image_sha256, source_gateway,
            )
            return RecognizeResult(
                outcome=outcome, validated=selected,
                candidates_for_user=(), score_attempt=attempt,
            )

        if outcome.decision == VisionRaceDecision.DISAGREEMENT:
            candidates = self._collect_candidates(outcome)
            return RecognizeResult(
                outcome=outcome, validated=outcome.selected,
                candidates_for_user=candidates, score_attempt=None,
            )

        if outcome.decision == VisionRaceDecision.GLOBAL_TIMEOUT:
            if outcome.selected is not None:
                return await self._adopt_timeout_result(
                    outcome, user_id, image_sha256, source_gateway,
                )
            # Return partial candidates from completed results even on timeout
            candidates = self._collect_candidates(outcome)
            return RecognizeResult(
                outcome=outcome, validated=None,
                candidates_for_user=candidates, score_attempt=None,
            )

        # ALL_FAILED, NO_AVAILABLE_ENGINES — no score
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), score_attempt=None,
        )

    @staticmethod
    def _collect_candidates(
        outcome: VisionRaceOutcome,
    ) -> tuple[Candidate, ...]:
        """Collect, dedup, and rank candidates from all engine results on disagreement.

        Iterates over every Successful engine result, flattens their
        :class:`ValidatedCandidate` entries, groups by
        ``(matched_chart_id, difficulty, judgements)`` to avoid merging
        different judgements for the same song, counts model support
        (number of unique engine identities that agree on that tuple),
        and ranks via the domain
        :func:`~pjsk_core.domain.ocr.rank_candidates` function.
        """
        # Group by (chart_id_or_song_id, difficulty, judgements)
        groups: dict[
            tuple[int, Difficulty, Judgements],
            list[tuple[EngineIdentity, ValidatedCandidate, OcrObservation]],
        ] = {}
        for result in outcome.results:
            if result.status != EngineResultStatus.SUCCESS:
                continue
            if result.validated is None or result.observation is None:
                continue
            obs = result.observation
            for vc in result.validated.candidates:
                chart_id = (
                    vc.chart.id
                    if vc.chart is not None
                    else vc.song_match.song_id
                )
                key = (chart_id, obs.difficulty, obs.judgements)
                if key not in groups:
                    groups[key] = []
                groups[key].append((result.identity, vc, obs))

        if not groups:
            return ()

        # Dedup per group — keep the highest-scoring match
        candidate_list: list[Candidate] = []
        for _key, entries in groups.items():
            # Sort by match score descending within the group
            entries.sort(key=lambda e: -e[1].song_match.score)
            best_vc = entries[0][1]
            obs = entries[0][2]
            # Count unique engine identities supporting this group
            supporting = {e[0].engine_id for e in entries}
            candidate_list.append(Candidate(
                observation=obs,
                model_support=len(supporting),
                note_validated=best_vc.note_validated,
                title_similarity=best_vc.song_match.score,
                note_distance=(
                    best_vc.note_distance
                    if best_vc.note_distance is not None
                    else 9999
                ),
                matched_chart_id=(
                    best_vc.chart.id
                    if best_vc.chart is not None
                    else None
                ),
            ))

        return tuple(rank_candidates(candidate_list))

    async def _record(
        self,
        selected: ValidatedObservation,
        user_id: UserId,
        image_sha256: str,
        source_gateway: str,
    ) -> ScoreAttempt:
        """Construct and persist a ScoreAttempt from a validated observation."""
        primary = selected.primary
        if primary is None:
            raise RuntimeError("Cannot record: selected has no primary candidate")
        chart = primary.chart
        if chart is None:
            raise RuntimeError("Cannot record: primary candidate has no chart")
        obs = selected.observation
        judgements = obs.judgements
        status = classify_status(judgements)
        accuracy = calculate_accuracy(judgements)
        rating = calculate_rating(
            chart.official_level, chart.community_constant,
            status, accuracy, chart.difficulty,
        )
        now = self._clock()
        attempt = ScoreAttempt(
            id=None, user_id=user_id, chart_id=chart.id,
            judgements=judgements, accuracy=accuracy,
            rating=rating, status=status,
            image_sha256=image_sha256, source_gateway=source_gateway,
            ocr_run_id=None, created_at=now,
        )
        return await self._scores.record_attempt(attempt)

    async def _adopt_timeout_result(
        self,
        outcome: VisionRaceOutcome,
        user_id: UserId,
        image_sha256: str,
        source_gateway: str,
    ) -> RecognizeResult:
        """Adopt a single STRONG result when global timeout fired.

        Only records if the selected observation has STRONG validation.
        """
        if (outcome.selected is None
                or outcome.selected.status != ValidationStatus.STRONG):
            return RecognizeResult(
                outcome=outcome, validated=None,
                candidates_for_user=(), score_attempt=None,
            )
        attempt = await self._record(
            outcome.selected, user_id, image_sha256, source_gateway,
        )
        return RecognizeResult(
            outcome=outcome, validated=outcome.selected,
            candidates_for_user=(), score_attempt=attempt,
        )
