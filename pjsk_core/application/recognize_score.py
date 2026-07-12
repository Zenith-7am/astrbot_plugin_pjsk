"""RecognizeScore use case — coordinate vision race, record on consensus/degraded."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass

from pjsk_core.application.vision_race import (
    VisionRace,
    VisionRaceDecision,
    VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.domain.ocr import Candidate
from pjsk_core.domain.scores import (
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
    ) -> None:
        self._race = race
        self._scores = scores

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
            # Collect candidates from all engine results
            # (simplified for now — full candidate merge in Phase 3b)
            return RecognizeResult(
                outcome=outcome, validated=outcome.selected,
                candidates_for_user=(), score_attempt=None,
            )

        if outcome.decision == VisionRaceDecision.GLOBAL_TIMEOUT:
            if outcome.selected is not None:
                return await self._adopt_timeout_result(
                    outcome, user_id, image_sha256, source_gateway,
                )
            return RecognizeResult(
                outcome=outcome, validated=None,
                candidates_for_user=(), score_attempt=None,
            )

        # ALL_FAILED, NO_AVAILABLE_ENGINES — no score
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), score_attempt=None,
        )

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
        now = datetime.now(timezone.utc)
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
