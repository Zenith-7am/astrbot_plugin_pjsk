"""Candidate store port — temporary OCR result storage for user confirmation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pjsk_core.domain.ocr import Candidate
    from pjsk_core.domain.users import UserId


class CandidateConsumeStatus(Enum):
    """Result of a consume_selection attempt."""
    OK = "ok"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    FORBIDDEN = "forbidden"
    INVALID_SELECTION = "invalid_selection"


@dataclass(frozen=True)
class CandidateConsumeResult:
    """Structured result from consume_selection.

    On OK, both ``candidate`` and ``candidate_set`` are present.
    On any other status, both are None.
    """
    status: CandidateConsumeStatus
    candidate: Candidate | None
    candidate_set: CandidateSet | None


@dataclass(frozen=True)
class CandidateSet:
    """A ranked set of disagreeing OCR candidates with enough context
    to construct a ScoreAttempt on user confirmation."""
    candidates: tuple[Candidate, ...]
    image_sha256: str
    source_gateway: str
    ocr_run_id: int
    chart_data_version: str


class CandidateStore(Protocol):
    """Short-lived storage for ambiguous OCR results awaiting user selection.

    Single-consumption: ``consume_selection`` atomically validates
    ownership, expiry, and selection index in one locked operation.
    Expired entries are swept on ``put``.
    """

    async def put(
        self,
        user_id: UserId,
        candidate_set: CandidateSet,
        ttl_seconds: int,
    ) -> str:
        """Store a candidate set and return a string ID for user reference."""
        ...

    async def consume_selection(
        self,
        candidate_set_id: str,
        user_id: UserId,
        selection: int,
    ) -> CandidateConsumeResult:
        """Atomically validate ownership, expiry, and index; delete and return
        on success. Returns structured status on any failure."""
        ...
