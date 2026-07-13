"""Tests for RecognizeScore use case — score construction and recording."""

from datetime import datetime, timezone

from pjsk_core.application.recognize_score import RecognizeScore
from pjsk_core.application.vision_race import (
    EngineResult,
    EngineResultStatus,
    VisionRaceDecision,
    VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate,
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
)
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.song_matcher import SongMatch, SongMatchMethod, TitleSource
from pjsk_core.domain.users import UserId


class _FakeScoreRepo:
    """In-memory fake for ScoreRepository."""

    def __init__(self) -> None:
        self.recorded: list[ScoreAttempt] = []

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        self.recorded.append(attempt)
        return attempt

    async def get_personal_best(
        self, user_id: UserId, chart_id: int,
    ) -> ScoreAttempt | None:
        return None

    async def list_personal_bests(
        self, user_id: UserId,
        status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        return []


class _FakeVisionRace:
    """Fake VisionRace returning a pre-set outcome."""

    def __init__(self, outcome: VisionRaceOutcome) -> None:
        self.outcome = outcome

    async def run(self, image: bytes) -> VisionRaceOutcome:
        return self.outcome


class _FakeOcrRunRecorder:
    """Fake OcrRunRecorder — returns a record with id=42."""

    def __init__(self) -> None:
        self.recorded: list[object] = []

    async def record(  # type: ignore[no-untyped-def]
        self, user_id, image_sha256, source_gateway, outcome,
    ) -> object:
        from datetime import datetime, timezone

        from pjsk_core.domain.ocr_runs import OcrRunRecord

        record = OcrRunRecord(
            id=42, user_id=user_id, image_sha256=image_sha256,
            source_gateway=source_gateway,
            final_state=outcome.decision.value if hasattr(outcome.decision, 'value') else str(outcome.decision),
            selected_engine=None, observations=(),
            created_at=datetime.now(timezone.utc),
        )
        self.recorded.append(record)
        return record


class _FakeCandidateStore:
    def __init__(self) -> None:
        self.put_calls: list[object] = []

    async def put(  # type: ignore[no-untyped-def]
        self, user_id, candidate_set, ttl_seconds,
    ) -> str:
        self.put_calls.append((user_id, candidate_set, ttl_seconds))
        return "cs-test-123"

    async def consume_selection(  # type: ignore[no-untyped-def]
        self, candidate_set_id, user_id, selection,
    ) -> None:
        raise NotImplementedError("Not needed for RecognizeScore tests")


class _FakeChartRepo:
    async def get_song_catalog(self) -> object:
        from pjsk_core.ports.repositories import SongCatalog

        return SongCatalog(version="v1", candidates=())

    async def get_by_id(  # type: ignore[no-untyped-def]
        self, chart_id,
    ) -> None:
        return None  # not needed for consensus tests


def _make_chart() -> Chart:
    return Chart(
        id=1, song_id=1, difficulty=Difficulty.MASTER,
        official_level=30, community_constant="30.5",
        note_count=1100, data_version="v1",
    )


def _make_strong_candidate(
    chart: Chart | None = None,
) -> ValidatedCandidate:
    if chart is None:
        chart = _make_chart()
    return ValidatedCandidate(
        song_match=SongMatch(
            song_id=1, score=1.0,
            method=SongMatchMethod.EXACT,
            source=TitleSource.JAPANESE,
        ),
        chart=chart, note_distance=0,
        note_validated=True, level_validated=True,
        status=ValidationStatus.STRONG,
    )


def _make_observation() -> OcrObservation:
    return OcrObservation(
        "Test Song", Difficulty.MASTER, 30,
        Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
        engine="test", elapsed_ms=100,
    )


def _make_validated_strong(
    primary: ValidatedCandidate | None = None,
) -> ValidatedObservation:
    if primary is None:
        primary = _make_strong_candidate()
    obs = _make_observation()
    return ValidatedObservation(
        observation=obs, primary=primary,
        candidates=(primary,) if primary is not None else (),
        status=ValidationStatus.STRONG,
    )


def _make_outcome(
    decision: VisionRaceDecision,
    selected: ValidatedObservation | None = None,
) -> VisionRaceOutcome:
    return VisionRaceOutcome(
        decision=decision, selected=selected, consensus=None,
        results=(), circuit_rejects=(),
    )


class TestRecognizeScore:
    """RecognizeScore use case tests."""

    async def test_consensus_records_score(self) -> None:
        """CONSENSUS decision should construct and record a ScoreAttempt."""
        validated = _make_validated_strong()
        outcome = _make_outcome(
            VisionRaceDecision.CONSENSUS, selected=validated,
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is not None
        assert result.score_attempt.user_id == UserId(1)
        assert result.score_attempt.source_gateway == "astrbot"
        assert result.score_attempt.chart_id == 1
        assert result.score_attempt.status == ScoreStatus.FC
        assert result.score_attempt.accuracy > 0
        assert result.score_attempt.rating > 0
        assert result.validated is not None
        assert len(repo.recorded) == 1

    async def test_degraded_single_records_score(self) -> None:
        """DEGRADED_SINGLE decision should also construct and record."""
        validated = _make_validated_strong()
        outcome = _make_outcome(
            VisionRaceDecision.DEGRADED_SINGLE, selected=validated,
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is not None
        assert result.score_attempt.user_id == UserId(1)
        assert len(repo.recorded) == 1

    async def test_disagreement_returns_no_score(self) -> None:
        """DISAGREEMENT decision should not record a score."""
        outcome = _make_outcome(VisionRaceDecision.DISAGREEMENT)

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert len(repo.recorded) == 0

    async def test_all_failed_no_score(self) -> None:
        """ALL_FAILED decision should not record a score."""
        outcome = _make_outcome(VisionRaceDecision.ALL_FAILED)

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert len(repo.recorded) == 0

    async def test_global_timeout_strong_records_score(self) -> None:
        """GLOBAL_TIMEOUT with single STRONG result adopts as degraded."""
        validated = _make_validated_strong()
        outcome = _make_outcome(
            VisionRaceDecision.GLOBAL_TIMEOUT, selected=validated,
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is not None
        assert result.validated is not None
        assert len(repo.recorded) == 1

    async def test_global_timeout_no_strong_no_score(self) -> None:
        """GLOBAL_TIMEOUT without STRONG validation should not record."""
        outcome = _make_outcome(VisionRaceDecision.GLOBAL_TIMEOUT)

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert result.validated is None
        assert len(repo.recorded) == 0

    async def test_no_available_engines_no_score(self) -> None:
        """NO_AVAILABLE_ENGINES decision should not record a score."""
        outcome = _make_outcome(VisionRaceDecision.NO_AVAILABLE_ENGINES)

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert len(repo.recorded) == 0

    async def test_consensus_without_primary_no_score(self) -> None:
        """CONSENSUS with selected having no primary should not record."""
        validated = ValidatedObservation(
            observation=_make_observation(),
            primary=None, candidates=(), status=ValidationStatus.STRONG,
        )
        outcome = _make_outcome(
            VisionRaceDecision.CONSENSUS, selected=validated,
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert len(repo.recorded) == 0

    async def test_clock_injection_used_for_created_at(self) -> None:
        """A custom clock should produce the expected created_at timestamp."""
        fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        validated = _make_validated_strong()
        outcome = _make_outcome(
            VisionRaceDecision.CONSENSUS, selected=validated,
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts, clock=lambda: fixed_time)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is not None
        assert result.score_attempt.created_at == fixed_time

    async def test_global_timeout_returns_partial_candidates(self) -> None:
        """GLOBAL_TIMEOUT without STRONG result should return candidates."""
        obs = OcrObservation(
            "Song A", Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        )
        chart = _make_chart()
        sm = SongMatch(
            song_id=1, score=0.9,
            method=SongMatchMethod.FUZZY,
            source=TitleSource.JAPANESE,
        )
        vc = ValidatedCandidate(
            song_match=sm, chart=chart, note_distance=0,
            note_validated=True, level_validated=True,
            status=ValidationStatus.CANDIDATE,
        )
        valid = ValidatedObservation(
            observation=obs, primary=None,
            candidates=(vc,), status=ValidationStatus.CANDIDATE,
        )
        results = (
            EngineResult(
                identity=EngineIdentity("g", "google", "g"),
                status=EngineResultStatus.SUCCESS,
                observation=obs, validated=valid,
                error=None, elapsed_ms=100,
            ),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.GLOBAL_TIMEOUT,
            selected=None, consensus=None,
            results=results, circuit_rejects=(),
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert len(result.candidates_for_user) == 1

    async def test_disagreement_candidates_grouped_by_full_key(self) -> None:
        """Different judgements for same song_id produce separate candidates."""
        obs1 = OcrObservation(
            "Song A", Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        )
        obs2 = OcrObservation(
            "Song A", Difficulty.MASTER, 30,
            Judgements(perfect=500, great=500, good=0, bad=0, miss=0),
            engine="z", elapsed_ms=100,
        )
        chart = _make_chart()
        sm = SongMatch(
            song_id=1, score=1.0,
            method=SongMatchMethod.EXACT,
            source=TitleSource.JAPANESE,
        )
        vc1 = ValidatedCandidate(
            song_match=sm, chart=chart, note_distance=0,
            note_validated=True, level_validated=True,
            status=ValidationStatus.STRONG,
        )
        vc2 = ValidatedCandidate(
            song_match=sm, chart=chart, note_distance=0,
            note_validated=True, level_validated=True,
            status=ValidationStatus.STRONG,
        )
        valid1 = ValidatedObservation(
            observation=obs1, primary=vc1,
            candidates=(vc1,), status=ValidationStatus.STRONG,
        )
        valid2 = ValidatedObservation(
            observation=obs2, primary=vc2,
            candidates=(vc2,), status=ValidationStatus.STRONG,
        )
        results = (
            EngineResult(
                identity=EngineIdentity("g", "google", "g"),
                status=EngineResultStatus.SUCCESS,
                observation=obs1, validated=valid1,
                error=None, elapsed_ms=100,
            ),
            EngineResult(
                identity=EngineIdentity("z", "zhipu", "z"),
                status=EngineResultStatus.SUCCESS,
                observation=obs2, validated=valid2,
                error=None, elapsed_ms=100,
            ),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.DISAGREEMENT,
            selected=None, consensus=None,
            results=results, circuit_rejects=(),
        )

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert len(result.candidates_for_user) == 2

    async def test_consensus_sets_ocr_run_id(self) -> None:
        """On CONSENSUS, ScoreAttempt.ocr_run_id comes from recorded OCR run."""
        validated = _make_validated_strong()
        outcome = _make_outcome(VisionRaceDecision.CONSENSUS, selected=validated)
        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(UserId(1), b"img", source_gateway="astrbot")
        assert result.score_attempt is not None
        assert result.score_attempt.ocr_run_id == 42

    async def test_disagreement_stores_candidates(self) -> None:
        """DISAGREEMENT stores candidates and returns candidate_set_id."""
        obs1 = OcrObservation(
            "Song A", Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        )
        obs2 = OcrObservation(
            "Song B", Difficulty.MASTER, 30,
            Judgements(perfect=500, great=500, good=0, bad=0, miss=0),
            engine="z", elapsed_ms=100,
        )
        chart = _make_chart()
        sm = SongMatch(song_id=1, score=1.0, method=SongMatchMethod.EXACT, source=TitleSource.JAPANESE)
        vc = ValidatedCandidate(
            song_match=sm, chart=chart, note_distance=0,
            note_validated=True, level_validated=True,
            status=ValidationStatus.STRONG,
        )
        valid = ValidatedObservation(
            observation=obs1, primary=vc, candidates=(vc,),
            status=ValidationStatus.STRONG,
        )
        results = (
            EngineResult(
                EngineIdentity("g", "google", "g"),
                EngineResultStatus.SUCCESS, obs1, valid, None, 100,
            ),
            EngineResult(
                EngineIdentity("z", "zhipu", "z"),
                EngineResultStatus.SUCCESS, obs2, valid, None, 100,
            ),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.DISAGREEMENT,
            selected=None, consensus=None,
            results=results, circuit_rejects=(),
        )
        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(UserId(1), b"img", source_gateway="astrbot")
        assert result.candidate_set_id == "cs-test-123"
        assert len(result.candidates_for_user) > 0
        assert result.score_attempt is None
        assert len(store.put_calls) == 1
