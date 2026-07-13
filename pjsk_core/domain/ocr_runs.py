"""OCR run audit records — domain types for persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


@dataclass(frozen=True)
class OcrEngineRecord:
    """Single engine's recognition outcome for audit persistence.

    Every configured engine produces one row, including those that were
    cancelled by consensus or rejected by the circuit breaker.
    """
    engine_id: str
    provider: str
    result_status: str
    elapsed_ms: int
    song_title: str | None
    difficulty: Difficulty | None
    displayed_level: int | None
    judgements: Judgements | None
    matched_chart_id: int | None
    validation_status: str | None
    error_type: str | None


@dataclass(frozen=True)
class OcrRunRecord:
    """Complete record of one OCR attempt — run + all engine observations."""
    id: int | None
    user_id: UserId
    image_sha256: str
    source_gateway: str
    final_state: str
    selected_engine: str | None
    observations: tuple[OcrEngineRecord, ...]
    created_at: datetime
