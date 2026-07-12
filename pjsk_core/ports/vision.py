"""Vision engine port — multi-model OCR for score screenshots."""

from typing import Protocol

from pjsk_core.domain.ocr import OcrObservation


class VisionEngine(Protocol):
    """A single vision model backend for recognizing score screenshots."""

    name: str

    async def recognize(
        self, image: bytes, *, timeout: float
    ) -> OcrObservation: ...
