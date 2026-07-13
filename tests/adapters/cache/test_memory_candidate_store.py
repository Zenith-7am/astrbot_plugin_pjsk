"""Tests for MemoryCandidateStore."""
import asyncio

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import Candidate, OcrObservation
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import (
    CandidateConsumeStatus,
    CandidateSet,
)
from adapters.cache.memory_candidate_store import MemoryCandidateStore


def _candidate(title: str = "Test Song", chart_id: int = 1) -> Candidate:
    return Candidate(
        observation=OcrObservation(
            title, Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        ),
        model_support=2, note_validated=True,
        title_similarity=1.0, note_distance=0,
        matched_chart_id=chart_id,
    )


def _candidate_set() -> CandidateSet:
    return CandidateSet(
        candidates=(_candidate("Song A", 1), _candidate("Song B", 2)),
        image_sha256="a" * 64, source_gateway="astrbot",
        ocr_run_id=1, chart_data_version="v1",
    )


class TestMemoryCandidateStore:
    async def test_put_and_consume_selection_ok(self) -> None:
        store = MemoryCandidateStore()
        cs = _candidate_set()
        cid = await store.put(UserId(1), cs, 300)
        assert cid is not None
        assert len(cid) == 12  # uuid4 hex[:12]

        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.OK
        assert result.candidate is not None
        assert result.candidate.matched_chart_id == 1
        assert result.candidate_set is not None

    async def test_consume_twice_returns_not_found(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)
        await store.consume_selection(cid, UserId(1), 1)
        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND

    async def test_wrong_user_returns_forbidden(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)
        result = await store.consume_selection(cid, UserId(2), 1)
        assert result.status == CandidateConsumeStatus.FORBIDDEN
        # Original owner can still consume
        result2 = await store.consume_selection(cid, UserId(1), 1)
        assert result2.status == CandidateConsumeStatus.OK

    async def test_invalid_selection_does_not_delete(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)
        result = await store.consume_selection(cid, UserId(1), 99)
        assert result.status == CandidateConsumeStatus.INVALID_SELECTION
        # Entry still exists — user can retry
        result2 = await store.consume_selection(cid, UserId(1), 1)
        assert result2.status == CandidateConsumeStatus.OK

    async def test_expired_returns_expired_and_deletes(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), ttl_seconds=0)
        # Force expiry by waiting slightly — TTL 0 means already expired
        await asyncio.sleep(0.01)
        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.EXPIRED
        # Second call returns NOT_FOUND (deleted on expiry check)
        result2 = await store.consume_selection(cid, UserId(1), 1)
        assert result2.status == CandidateConsumeStatus.NOT_FOUND

    async def test_put_sweeps_expired_entries(self) -> None:
        store = MemoryCandidateStore()
        # Put with 0 TTL — expires immediately
        cid = await store.put(UserId(1), _candidate_set(), ttl_seconds=0)
        await asyncio.sleep(0.01)
        # Put another — should sweep the expired one
        cid2 = await store.put(UserId(2), _candidate_set(), 300)
        # Expired entry should be gone
        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND
        # New entry should still be there
        result2 = await store.consume_selection(cid2, UserId(2), 1)
        assert result2.status == CandidateConsumeStatus.OK

    async def test_evicts_oldest_when_full(self) -> None:
        store = MemoryCandidateStore(max_entries=2)
        cid1 = await store.put(UserId(1), _candidate_set(), 300)
        await asyncio.sleep(0.01)  # ensure different expiry times
        cid2 = await store.put(UserId(1), _candidate_set(), 300)
        # Third put should evict cid1 (oldest)
        cid3 = await store.put(UserId(1), _candidate_set(), 300)
        # cid1 should be NOT_FOUND since it was evicted
        result = await store.consume_selection(cid1, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND
        # cid2 and cid3 should still be accessible
        r2 = await store.consume_selection(cid2, UserId(1), 1)
        assert r2.status == CandidateConsumeStatus.OK
        r3 = await store.consume_selection(cid3, UserId(1), 1)
        assert r3.status == CandidateConsumeStatus.OK

    async def test_nonexistent_id_returns_not_found(self) -> None:
        store = MemoryCandidateStore()
        result = await store.consume_selection("nonexistent", UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND

    async def test_concurrent_consume_atomic(self) -> None:
        """Two concurrent consumes — only one succeeds."""
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)

        async def consume() -> CandidateConsumeStatus:
            result = await store.consume_selection(cid, UserId(1), 1)
            return result.status

        results = await asyncio.gather(consume(), consume())
        oks = [r for r in results if r == CandidateConsumeStatus.OK]
        not_founds = [r for r in results if r == CandidateConsumeStatus.NOT_FOUND]
        assert len(oks) == 1
        assert len(not_founds) == 1
