"""Candidate store port — temporary OCR result storage for user confirmation."""

from typing import Protocol

from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.users import UserId


class CandidateStore(Protocol):
    """Temporary storage for ambiguous OCR results awaiting user selection.

    Each candidate set is single-consumption with a TTL.
    """

    async def put(
        self,
        user_id: UserId,
        candidates: list[OcrObservation],
        ttl_seconds: int,
    ) -> str: ...

    async def consume(
        self, candidate_set_id: str
    ) -> list[OcrObservation] | None: ...
