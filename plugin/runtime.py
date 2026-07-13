"""PluginRuntime — holds all long-lived resources for the PJSK plugin."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import aiosqlite
import httpx

from plugin.rate_limiter import UserRateLimiter
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
    rate_limiter: UserRateLimiter
    http_client: httpx.AsyncClient | None = None
    db_conn: aiosqlite.Connection | None = None
    pending_candidate_sets: dict[int, str] = field(default_factory=dict)
    pending_display_text: dict[int, str] = field(default_factory=dict)

    async def close(self) -> None:
        """Release resources. Idempotent — safe to call multiple times."""
        await self.image_buffer.close()
        if self.http_client is not None:
            await self.http_client.aclose()
        if self.db_conn is not None:
            await self.db_conn.close()
