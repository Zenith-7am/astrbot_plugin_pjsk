"""PluginRuntime — holds all long-lived resources for the PJSK plugin."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pjsk_core.application.confirm_candidate import ConfirmCandidate
from pjsk_core.application.recognize_score import RecognizeScore
from pjsk_core.ports.cache import CandidateStore
from pjsk_core.ports.ocr_runs import OcrRunRepository
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    UserRepository,
)


class EphemeralImageBuffer(Protocol):
    """In-memory buffer for group-chat images awaiting @Bot trigger."""
    def put(self, platform_id: str, group_id: str, sender_qq: object, image_bytes: bytes) -> None: ...
    def consume(self, platform_id: str, group_id: str, sender_qq: object, *, within_seconds: float = 15.0) -> bytes | None: ...
    async def close(self) -> None: ...


@dataclass
class PluginRuntime:
    """All long-lived resources assembled at plugin startup."""

    user_repo: UserRepository
    chart_repo: ChartRepository
    score_repo: ScoreRepository
    ocr_run_repo: OcrRunRepository
    recognize_score: RecognizeScore
    confirm_candidate: ConfirmCandidate
    candidate_store: CandidateStore
    image_buffer: EphemeralImageBuffer

    async def close(self) -> None:
        """Release resources. Idempotent — safe to call multiple times."""
        await self.image_buffer.close()
