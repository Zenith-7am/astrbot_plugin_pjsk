"""ConfirmCandidate — resolve a disagreeing OCR run by user selection."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pjsk_core.domain.scores import (
    ScoreAttempt,
    calculate_accuracy,
    classify_status,
)
from pjsk_core.domain.rating import calculate_rating
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import CandidateConsumeStatus, CandidateStore
from pjsk_core.ports.repositories import ChartRepository, ScoreRepository

_logger = logging.getLogger(__name__)


class ConfirmError(Enum):
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    FORBIDDEN = "forbidden"
    INVALID_SELECTION = "invalid_selection"
    NOT_CONFIRMABLE = "not_confirmable"


@dataclass(frozen=True)
class ConfirmResult:
    score_attempt: ScoreAttempt | None
    error: ConfirmError | None


class ConfirmCandidate:
    """Resolve a disagreeing OCR run by user candidate selection.

    Validates the selected candidate against live chart data before
    recording — the user can decide which song this is, but cannot
    override note-count or difficulty mismatches.
    """

    def __init__(
        self,
        store: CandidateStore,
        scores: ScoreRepository,
        charts: ChartRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._scores = scores
        self._charts = charts
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def confirm(
        self,
        user_id: UserId,
        candidate_set_id: str,
        selection: int,
    ) -> ConfirmResult:
        consume_result = await self._store.consume_selection(
            candidate_set_id, user_id, selection,
        )

        # Map store status to ConfirmError
        status_map = {
            CandidateConsumeStatus.NOT_FOUND: ConfirmError.NOT_FOUND,
            CandidateConsumeStatus.EXPIRED: ConfirmError.EXPIRED,
            CandidateConsumeStatus.FORBIDDEN: ConfirmError.FORBIDDEN,
            CandidateConsumeStatus.INVALID_SELECTION: ConfirmError.INVALID_SELECTION,
        }
        if consume_result.status in status_map:
            return ConfirmResult(None, status_map[consume_result.status])

        # OK — validate confirmability
        candidate = consume_result.candidate
        cs = consume_result.candidate_set
        if candidate is None or cs is None:
            return ConfirmResult(None, ConfirmError.NOT_FOUND)

        # 1. Must have a matched chart
        if candidate.matched_chart_id is None:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 2. Note validation must have passed
        if not candidate.note_validated:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 3. Chart must still exist
        chart = await self._charts.get_by_id(candidate.matched_chart_id)
        if chart is None:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 3b. Warn if chart_data_version differs (but still allow confirmation)
        if cs.chart_data_version != chart.data_version:
            _logger.warning(
                "chart_data_version mismatch on confirm: candidate_set=%s chart=%s for chart_id=%d",
                cs.chart_data_version, chart.data_version, chart.id,
            )

        # 4. Difficulty must match
        if candidate.observation.difficulty != chart.difficulty:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 5. Note count ±1
        total_judges = sum([
            candidate.observation.judgements.perfect,
            candidate.observation.judgements.great,
            candidate.observation.judgements.good,
            candidate.observation.judgements.bad,
            candidate.observation.judgements.miss,
        ])
        if abs(total_judges - chart.note_count) > 1:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # Construct and record ScoreAttempt
        judgements = candidate.observation.judgements
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
            image_sha256=cs.image_sha256,
            source_gateway=cs.source_gateway,
            ocr_run_id=cs.ocr_run_id,
            created_at=now,
        )
        recorded = await self._scores.record_attempt(attempt)
        return ConfirmResult(recorded, None)
