"""OCR run repository port."""
from typing import Protocol

from pjsk_core.domain.ocr_runs import OcrRunRecord


class OcrRunRepository(Protocol):
    """Persistence for OCR run audit records."""

    async def save(self, record: OcrRunRecord) -> OcrRunRecord: ...
    async def get_by_id(self, run_id: int) -> OcrRunRecord | None: ...
