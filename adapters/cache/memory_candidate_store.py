"""In-memory CandidateStore — dict-backed with asyncio.Lock, expiry sweep on put."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import (
    CandidateConsumeResult,
    CandidateConsumeStatus,
    CandidateSet,
)


@dataclass
class _Entry:
    candidate_set: CandidateSet
    user_id: UserId
    expires_at: float  # monotonic timestamp


class MemoryCandidateStore:
    """In-memory single-consumption candidate storage.

    No external dependencies. Restart loses all pending candidates
    (acceptable — this is a cache, not persistence).

    Expired entries are swept on ``put()``. When the entry count
    reaches ``max_entries``, the entry with the earliest expiry is
    evicted before inserting the new one.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries

    async def put(
        self,
        user_id: UserId,
        candidate_set: CandidateSet,
        ttl_seconds: int,
    ) -> str:
        cid = uuid.uuid4().hex[:12]
        now = time.monotonic()
        async with self._lock:
            # Sweep expired entries
            expired = [
                k for k, v in self._entries.items()
                if now > v.expires_at
            ]
            for k in expired:
                del self._entries[k]
            # Evict oldest if at capacity
            if len(self._entries) >= self._max_entries:
                oldest = min(
                    self._entries.keys(),
                    key=lambda k: self._entries[k].expires_at,
                )
                del self._entries[oldest]
            self._entries[cid] = _Entry(
                candidate_set=candidate_set,
                user_id=user_id,
                expires_at=now + ttl_seconds,
            )
        return cid

    async def consume_selection(
        self,
        candidate_set_id: str,
        user_id: UserId,
        selection: int,
    ) -> CandidateConsumeResult:
        async with self._lock:
            # 1. Check existence — BEFORE any mutation
            entry = self._entries.get(candidate_set_id)
            if entry is None:
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.NOT_FOUND,
                    candidate=None, candidate_set=None,
                )
            # 2. Check ownership — BEFORE delete
            if entry.user_id != user_id:
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.FORBIDDEN,
                    candidate=None, candidate_set=None,
                )
            # 3. Check expiry
            if time.monotonic() > entry.expires_at:
                del self._entries[candidate_set_id]
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.EXPIRED,
                    candidate=None, candidate_set=None,
                )
            # 4. Check selection bounds
            cs = entry.candidate_set
            if selection < 1 or selection > len(cs.candidates):
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.INVALID_SELECTION,
                    candidate=None, candidate_set=None,
                )
            # 5. All checks passed — atomically delete and return
            del self._entries[candidate_set_id]
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.OK,
                candidate=cs.candidates[selection - 1],
                candidate_set=cs,
            )
