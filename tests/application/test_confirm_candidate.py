"""Tests for ConfirmCandidate — user selection → score recording."""
import asyncio

from pjsk_core.application.confirm_candidate import (
    ConfirmCandidate,
    ConfirmError,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import Candidate, OcrObservation
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import (
    CandidateConsumeResult,
    CandidateConsumeStatus,
    CandidateSet,
)
from pjsk_core.ports.repositories import SongCatalog


# ── Fakes ──────────────────────────────────────────────────────────────

class _FakeCandidateStore:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[UserId, CandidateSet]] = {}
        self._lock = asyncio.Lock()

    async def put(self, user_id: UserId, cs: CandidateSet, ttl: int) -> str:
        key = f"cs-{len(self._entries)}"
        async with self._lock:
            self._entries[key] = (user_id, cs)
        return key

    async def consume_selection(
        self, cid: str, user_id: UserId, selection: int,
    ) -> CandidateConsumeResult:
        async with self._lock:
            entry = self._entries.pop(cid, None)
        if entry is None:
            return CandidateConsumeResult(
                CandidateConsumeStatus.NOT_FOUND, None, None)
        owner, cs = entry
        if owner != user_id:
            return CandidateConsumeResult(
                CandidateConsumeStatus.FORBIDDEN, None, None)
        if selection < 1 or selection > len(cs.candidates):
            return CandidateConsumeResult(
                CandidateConsumeStatus.INVALID_SELECTION, None, None)
        return CandidateConsumeResult(
            CandidateConsumeStatus.OK,
            cs.candidates[selection - 1], cs)


class _FakeScoreRepo:
    def __init__(self) -> None:
        self.recorded: list[ScoreAttempt] = []

    async def record_attempt(self, a: ScoreAttempt) -> ScoreAttempt:
        self.recorded.append(a)
        return a

    async def get_personal_best(self, uid: UserId, cid: int) -> ScoreAttempt | None:
        return None

    async def list_personal_bests(
        self, uid: UserId, sf: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        return []

    async def get_b20(
        self, user_id: UserId, include_append: bool,
    ) -> list[ScoreAttempt]:
        return []

    async def list_personal_bests_for_difficulty(
        self, user_id: UserId, chart_ids: list[int],
    ) -> dict[int, ScoreAttempt]:
        return {}


class _FakeChartRepo:
    def __init__(self, chart: Chart | None = None) -> None:
        self._chart = chart or Chart(
            id=1, song_id=1, difficulty=Difficulty.MASTER,
            official_level=30, community_constant="30.5",
            note_count=1100, data_version="v1",
        )

    async def get_by_id(self, chart_id: int) -> Chart | None:
        if chart_id == self._chart.id:
            return self._chart
        return None

    async def find_by_song_and_difficulty(
        self, title: str, diff: Difficulty,
    ) -> Chart | None:
        return None

    async def list_by_difficulty_level(
        self, diff: Difficulty, level: int,
    ) -> list[Chart]:
        return []

    async def get_song_catalog(self) -> SongCatalog:
        return SongCatalog(version="v1", candidates=())

    async def get_by_song_and_difficulty(
        self, song_id: int, diff: Difficulty,
    ) -> Chart | None:
        return None


# ── Helpers ────────────────────────────────────────────────────────────

def _candidate(chart_id: int = 1, note_validated: bool = True) -> Candidate:
    return Candidate(
        observation=OcrObservation(
            "Test Song", Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        ),
        model_support=2, note_validated=note_validated,
        title_similarity=1.0, note_distance=0, matched_chart_id=chart_id,
    )


def _cs(candidates: tuple[Candidate, ...] | None = None) -> CandidateSet:
    if candidates is None:
        candidates = (_candidate(),)
    return CandidateSet(
        candidates=candidates, image_sha256="a" * 64,
        source_gateway="astrbot", ocr_run_id=1, chart_data_version="v1",
    )


# ── Tests ──────────────────────────────────────────────────────────────

class TestConfirmCandidate:
    async def test_confirm_records_score(self) -> None:
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()
        cc = ConfirmCandidate(store, scores, charts)
        cs_ = _cs()
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error is None
        assert result.score_attempt is not None
        assert result.score_attempt.chart_id == 1
        assert result.score_attempt.ocr_run_id == 1
        assert result.score_attempt.source_gateway == "astrbot"
        assert len(scores.recorded) == 1

    async def test_not_found(self) -> None:
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()
        cc = ConfirmCandidate(store, scores, charts)
        result = await cc.confirm(UserId(1), "nonexistent", 1)
        assert result.error == ConfirmError.NOT_FOUND
        assert result.score_attempt is None

    async def test_fails_not_confirmable_no_chart(self) -> None:
        """Candidate with chart_id=None is not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()
        cc = ConfirmCandidate(store, scores, charts)
        bad = Candidate(
            observation=OcrObservation(
                "X", Difficulty.MASTER, 30,
                Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                engine="g", elapsed_ms=100,
            ),
            model_support=1, note_validated=True,
            title_similarity=0.5, note_distance=0, matched_chart_id=None,
        )
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE

    async def test_fails_not_confirmable_note_not_validated(self) -> None:
        """Candidate with note_validated=False is not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()  # chart has note_count=1100
        cc = ConfirmCandidate(store, scores, charts)
        # judgements sum = 10, chart note_count = 1100 → diff = 1090 > 1
        bad = _candidate(note_validated=False)
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE

    async def test_fails_not_confirmable_wrong_difficulty(self) -> None:
        """Candidate difficulty != chart difficulty → not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        # Chart is MASTER, but candidate says EXPERT
        chart = Chart(
            id=1, song_id=1, difficulty=Difficulty.MASTER,
            official_level=30, community_constant="30.5",
            note_count=1100, data_version="v1",
        )
        charts = _FakeChartRepo(chart)
        cc = ConfirmCandidate(store, scores, charts)
        bad = Candidate(
            observation=OcrObservation(
                "X", Difficulty.EXPERT, 25,
                Judgements(perfect=1100, great=0, good=0, bad=0, miss=0),
                engine="g", elapsed_ms=100,
            ),
            model_support=1, note_validated=True,
            title_similarity=0.5, note_distance=0, matched_chart_id=1,
        )
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE

    async def test_confirm_with_chart_not_found(self) -> None:
        """chart_id doesn't exist in database → not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()  # only chart_id=1 exists
        cc = ConfirmCandidate(store, scores, charts)
        bad = _candidate(chart_id=999)
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE
