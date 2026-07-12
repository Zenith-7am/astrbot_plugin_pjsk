"""Tests for RecognizeScore use case — score construction and recording."""

from pjsk_core.application.recognize_score import RecognizeScore
from pjsk_core.application.vision_race import (
    VisionRaceDecision,
    VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate,
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import OcrObservation
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
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
        recognize = RecognizeScore(race, repo)  # type: ignore[arg-type]
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is None
        assert len(repo.recorded) == 0
