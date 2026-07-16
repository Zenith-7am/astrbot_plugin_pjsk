"""Runtime — holds all long-lived resources with lifecycle tracking."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import aiosqlite
import httpx

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
from pjsk_emubot.rate_limiter import UserRateLimiter

# ── Lifecycle ────────────────────────────────────────────────────────────────


class RuntimeStatus(Enum):
    """Ordered lifecycle states for the Runtime."""

    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"


# ── Ports that live in the runtime layer ─────────────────────────────────────


class EphemeralImageBuffer(Protocol):
    """In-memory buffer for group-chat images awaiting @Bot trigger."""

    def put(
        self, platform_id: str, group_id: str,
        sender_qq: object, image_bytes: bytes,
    ) -> None: ...

    def consume(
        self, platform_id: str, group_id: str, sender_qq: object,
        *, within_seconds: float = 15.0,
    ) -> bytes | None: ...

    def arm(
        self, platform_id: str, group_id: str, sender_qq: object,
    ) -> None: ...

    def consume_arm(
        self, platform_id: str, group_id: str, sender_qq: object,
        *, within_seconds: float = 15.0,
    ) -> bool: ...

    async def close(self) -> None: ...


# ── Runtime ──────────────────────────────────────────────────────────────────


@dataclass
class Runtime:
    """All long-lived resources assembled at startup.

    Lifecycle: STARTING → READY/DEGRADED → STOPPING → STOPPED.
    ``close()`` is idempotent — safe to call multiple times.
    """

    # ── Repositories ─────────────────────────────────────────────────────
    user_repo: UserRepository
    chart_repo: ChartRepository
    score_repo: ScoreRepository
    song_repo: SongRepository
    ocr_run_repo: OcrRunRepository

    # ── Application use cases ────────────────────────────────────────────
    confirm_candidate: ConfirmCandidate
    candidate_store: CandidateStore
    query_b20: QueryB20
    query_difficulty_ranking: QueryDifficultyRanking
    toggle_append: ToggleAppend
    recognize_score: RecognizeScore | None = None
    renderer: Renderer | None = None
    jacket_cache: Any | None = None

    # ── Infrastructure ───────────────────────────────────────────────────
    image_buffer: EphemeralImageBuffer | None = None
    rate_limiter: UserRateLimiter | None = None
    http_client: httpx.AsyncClient | None = None

    # ── Database connections (kept for backward compat; prefer UoW) ─────
    db_conn: aiosqlite.Connection | None = None
    chart_db_conn: aiosqlite.Connection | None = None
    score_db_conn: aiosqlite.Connection | None = None

    # ── Pending candidate state ──────────────────────────────────────────
    _pending_sets: dict[tuple[int, str, str], str] = field(default_factory=dict)
    _pending_display: dict[tuple[int, str, str], str] = field(default_factory=dict)

    # ── Lifecycle ────────────────────────────────────────────────────────
    _status: RuntimeStatus = field(default=RuntimeStatus.STARTING, init=False)

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    def mark_ready(self) -> None:
        """Transition from STARTING → READY after bootstrap completes."""
        if self._status == RuntimeStatus.STARTING:
            self._status = RuntimeStatus.READY

    def mark_degraded(self, reason: str | None = None) -> None:
        """Mark runtime as degraded (non-fatal issue, still serving)."""
        self._status = RuntimeStatus.DEGRADED
        if reason:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning("Runtime degraded: %s", reason)

    # ── Candidate pending state ──────────────────────────────────────────

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
        return self._pending_sets.get((user_id, platform_id, conversation_id))

    def get_pending_display_text(
        self, user_id: int, platform_id: str, conversation_id: str,
    ) -> str | None:
        return self._pending_display.get((user_id, platform_id, conversation_id))

    def clear_pending(
        self, user_id: int, platform_id: str, conversation_id: str,
    ) -> None:
        key = (user_id, platform_id, conversation_id)
        self._pending_sets.pop(key, None)
        self._pending_display.pop(key, None)

    # ── Shutdown ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release resources. Idempotent — safe to call multiple times."""
        if self._status == RuntimeStatus.STOPPED:
            return
        self._status = RuntimeStatus.STOPPING

        if self.image_buffer is not None:
            await self.image_buffer.close()
        if self.http_client is not None:
            await self.http_client.aclose()
        for conn in (self.db_conn, self.chart_db_conn, self.score_db_conn):
            if conn is not None:
                await conn.close()

        self._status = RuntimeStatus.STOPPED
