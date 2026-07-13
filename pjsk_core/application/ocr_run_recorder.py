"""OcrRunRecorder — persist every OCR attempt for audit/debugging."""
from __future__ import annotations

from datetime import datetime, timezone

from pjsk_core.application.vision_race import (
    EngineResult,
    EngineResultStatus,
    VisionRaceOutcome,
)
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.users import UserId
from pjsk_core.ports.ocr_runs import OcrRunRepository


class OcrRunRecorder:
    """Record every OCR attempt for audit/debugging.

    Call after VisionRace.run() completes, regardless of outcome.
    Returns the persisted OcrRunRecord with database-assigned id.
    """

    def __init__(self, repo: OcrRunRepository) -> None:
        self._repo = repo

    async def record(
        self,
        user_id: UserId,
        image_sha256: str,
        source_gateway: str,
        outcome: VisionRaceOutcome,
    ) -> OcrRunRecord:
        """Build and persist OcrRunRecord from a completed vision race."""
        engine_records: list[OcrEngineRecord] = []

        for result in outcome.results:
            obs = result.observation
            validated = result.validated
            primary = validated.primary if validated else None

            engine_records.append(OcrEngineRecord(
                engine_id=result.identity.engine_id,
                provider=result.identity.provider,
                result_status=result.status.value,
                elapsed_ms=result.elapsed_ms,
                song_title=obs.song_title if obs else None,
                difficulty=obs.difficulty if obs else None,
                displayed_level=obs.displayed_level if obs else None,
                judgements=obs.judgements if obs else None,
                matched_chart_id=(
                    primary.chart.id
                    if primary and primary.chart
                    else None
                ),
                validation_status=(
                    validated.status.value if validated else None
                ),
                error_type=_error_type_from_result(result),
            ))

        # Circuit-rejected engines — never produced an EngineResult
        for identity in outcome.circuit_rejects:
            engine_records.append(OcrEngineRecord(
                engine_id=identity.engine_id,
                provider=identity.provider,
                result_status="circuit_rejected",
                elapsed_ms=0,
                song_title=None, difficulty=None, displayed_level=None,
                judgements=None, matched_chart_id=None,
                validation_status=None, error_type=None,
            ))

        selected_engine: str | None = None
        if outcome.consensus and outcome.consensus.supporting_engines:
            selected_engine = outcome.consensus.supporting_engines[0].engine_id
        elif outcome.selected and outcome.selected.primary:
            # Degraded single — extract from first successful result
            for result in outcome.results:
                if result.status == EngineResultStatus.SUCCESS:
                    selected_engine = result.identity.engine_id
                    break

        record = OcrRunRecord(
            id=None,
            user_id=user_id,
            image_sha256=image_sha256,
            source_gateway=source_gateway,
            final_state=outcome.decision.value,
            selected_engine=selected_engine,
            observations=tuple(engine_records),
            created_at=datetime.now(timezone.utc),
        )
        return await self._repo.save(record)


def _error_type_from_result(result: EngineResult) -> str | None:
    """Extract error_type string from an EngineResult's error."""
    if result.error is None:
        return None
    from pjsk_core.domain.ocr import (
        VisionConnectionError,
        VisionRateLimitError,
        VisionServerError,
        VisionTimeoutError,
    )
    if isinstance(result.error, VisionTimeoutError):
        return "timeout"
    if isinstance(result.error, VisionConnectionError):
        return "connection"
    if isinstance(result.error, VisionRateLimitError):
        return "rate_limited"
    if isinstance(result.error, VisionServerError):
        return "server_error"
    return "invalid_response"
