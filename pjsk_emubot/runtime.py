"""PluginRuntime — holds all long-lived resources for the PJSK plugin."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import aiosqlite
import httpx

from pjsk_emubot.rate_limiter import UserRateLimiter
from pjsk_core.application.confirm_candidate import ConfirmCandidate
from pjsk_core.application.query_b20 import QueryB20
from pjsk_core.application.query_difficulty_ranking import QueryDifficultyRanking
from pjsk_core.application.recognize_score import RecognizeScore
from pjsk_core.application.toggle_append import ToggleAppend
from pjsk_core.ports.cache import CandidateStore
from pjsk_core.ports.ocr_runs import OcrRunRepository
from pjsk_core.ports.renderer import Renderer
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    SongRepository,
    UserRepository,
)


class EphemeralImageBuffer(Protocol):
    """In-memory buffer for group-chat images awaiting @Bot trigger."""
    def put(self, platform_id: str, group_id: str, sender_qq: object, image_bytes: bytes) -> None: ...
    def consume(self, platform_id: str, group_id: str, sender_qq: object, *, within_seconds: float = 15.0) -> bytes | None: ...
    def arm(self, platform_id: str, group_id: str, sender_qq: object) -> None: ...
    def consume_arm(self, platform_id: str, group_id: str, sender_qq: object, *, within_seconds: float = 15.0) -> bool: ...
    async def close(self) -> None: ...


@dataclass
class PluginRuntime:
    """All long-lived resources assembled at plugin startup."""

    user_repo: UserRepository
    chart_repo: ChartRepository
    score_repo: ScoreRepository
    song_repo: SongRepository
    ocr_run_repo: OcrRunRepository
    confirm_candidate: ConfirmCandidate
    candidate_store: CandidateStore
    image_buffer: EphemeralImageBuffer
    rate_limiter: UserRateLimiter
    query_b20: QueryB20
    query_difficulty_ranking: QueryDifficultyRanking
    toggle_append: ToggleAppend
    recognize_score: RecognizeScore | None = None
    renderer: Renderer | None = None
    http_client: httpx.AsyncClient | None = None
    db_conn: aiosqlite.Connection | None = None
    chart_db_conn: aiosqlite.Connection | None = None
    score_db_conn: aiosqlite.Connection | None = None
    _pending_sets: dict[tuple[int, str, str], str] = field(default_factory=dict)
    _pending_display: dict[tuple[int, str, str], str] = field(default_factory=dict)

    def set_pending(
        self, user_id: int, platform_id: str, conversation_id: str,
        cid: str, display: str,
    ) -> None:
        """Store a pending candidate set for a user+platform+conversation."""
        key = (user_id, platform_id, conversation_id)
        self._pending_sets[key] = cid
        self._pending_display[key] = display

    def get_pending_candidate_set_id(
        self, user_id: int, platform_id: str, conversation_id: str,
    ) -> str | None:
        """Return the candidate set ID for this user+platform+conversation, or None."""
        return self._pending_sets.get((user_id, platform_id, conversation_id))

    def get_pending_display_text(
        self, user_id: int, platform_id: str, conversation_id: str,
    ) -> str | None:
        """Return the display text for this user+platform+conversation, or None."""
        return self._pending_display.get((user_id, platform_id, conversation_id))

    def clear_pending(
        self, user_id: int, platform_id: str, conversation_id: str,
    ) -> None:
        """Remove pending candidates for this user+platform+conversation."""
        key = (user_id, platform_id, conversation_id)
        self._pending_sets.pop(key, None)
        self._pending_display.pop(key, None)

    async def close(self) -> None:
        """Release resources. Idempotent — safe to call multiple times."""
        await self.image_buffer.close()
        if self.http_client is not None:
            await self.http_client.aclose()
        for conn in (self.db_conn, self.chart_db_conn, self.score_db_conn):
            if conn is not None:
                await conn.close()
