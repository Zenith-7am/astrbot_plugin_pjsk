"""Unified reply types for gateway-agnostic responses.

Gateways convert these into platform-specific messages
(AstrBot MessageEventResult, OneBot CQ codes, etc.).
"""

from dataclasses import dataclass

from pjsk_core.domain.ocr import OcrObservation


@dataclass(frozen=True)
class TextReply:
    """Plain text response."""

    text: str


@dataclass(frozen=True)
class ImageReply:
    """Rendered image response."""

    image_bytes: bytes
    mime_type: str


@dataclass(frozen=True)
class CandidateReply:
    """Ambiguous OCR result — presents numbered candidates for user selection."""

    candidate_set_id: str
    candidates: list[OcrObservation]


@dataclass(frozen=True)
class ProgressReply:
    """Processing status update for long-running operations."""

    message: str
    current: int
    total: int


@dataclass(frozen=True)
class ErrorReply:
    """Error response with recoverability hint."""

    message: str
    recoverable: bool
