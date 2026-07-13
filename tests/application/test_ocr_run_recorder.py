"""Tests for OcrRunRecorder — audit trail construction from VisionRaceOutcome."""
from pjsk_core.application.ocr_run_recorder import OcrRunRecorder
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
    VisionTimeoutError,
)
from pjsk_core.domain.ocr_runs import OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.song_matcher import SongMatch, SongMatchMethod, TitleSource
from pjsk_core.domain.users import UserId


def _obs(title: str = "Test Song") -> OcrObservation:
    return OcrObservation(
        title, Difficulty.MASTER, 30,
        Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        engine="g", elapsed_ms=100,
    )


def _chart() -> Chart:
    return Chart(
        id=1, song_id=1, difficulty=Difficulty.MASTER,
        official_level=30, community_constant="30.5",
        note_count=1100, data_version="v1",
    )


def _make_validated_strong() -> ValidatedObservation:
    sm = SongMatch(song_id=1, score=1.0, method=SongMatchMethod.EXACT, source=TitleSource.JAPANESE)
    vc = ValidatedCandidate(
        song_match=sm, chart=_chart(), note_distance=0,
        note_validated=True, level_validated=True,
        status=ValidationStatus.STRONG,
    )
    return ValidatedObservation(
        observation=_obs(), primary=vc, candidates=(vc,),
        status=ValidationStatus.STRONG,
    )


class FakeOcrRunRepo:
    def __init__(self) -> None:
        self.saved: list[OcrRunRecord] = []
        self._next_id = 1

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        stored = OcrRunRecord(
            id=self._next_id, user_id=record.user_id,
            image_sha256=record.image_sha256,
            source_gateway=record.source_gateway,
            final_state=record.final_state,
            selected_engine=record.selected_engine,
            observations=record.observations,
            created_at=record.created_at,
        )
        self._next_id += 1
        self.saved.append(stored)
        return stored

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        for r in self.saved:
            if r.id == run_id:
                return r
        return None


class TestOcrRunRecorder:
    async def test_records_consensus_outcome(self) -> None:
        repo = FakeOcrRunRepo()
        recorder = OcrRunRecorder(repo)
        validated = _make_validated_strong()
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.CONSENSUS,
            selected=validated, consensus=None,
            results=(
                EngineResult(
                    identity=EngineIdentity("g", "google", "gemini-flash"),
                    status=EngineResultStatus.SUCCESS,
                    observation=_obs(), validated=validated,
                    error=None, elapsed_ms=100,
                ),
                EngineResult(
                    identity=EngineIdentity("s", "stepfun", "stepfun-vision"),
                    status=EngineResultStatus.CANCELLED_BY_CONSENSUS,
                    observation=None, validated=None,
                    error=None, elapsed_ms=50,
                ),
            ),
            circuit_rejects=(),
        )
        record = await recorder.record(
            UserId(1), "a" * 64, "astrbot", outcome,
        )
        assert record.id == 1
        assert record.final_state == "consensus"
        assert record.selected_engine == "g"
        assert len(record.observations) == 2
        success_obs = [o for o in record.observations if o.result_status == "success"]
        cancelled_obs = [o for o in record.observations if o.result_status == "cancelled_by_consensus"]
        assert len(success_obs) == 1
        assert len(cancelled_obs) == 1
        assert success_obs[0].song_title == "Test Song"

    async def test_records_all_failed(self) -> None:
        repo = FakeOcrRunRepo()
        recorder = OcrRunRecorder(repo)
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.ALL_FAILED,
            selected=None, consensus=None,
            results=(
                EngineResult(
                    identity=EngineIdentity("g", "google", "g"),
                    status=EngineResultStatus.FAILED,
                    observation=None, validated=None,
                    error=VisionTimeoutError("timeout"), elapsed_ms=5000,
                ),
            ),
            circuit_rejects=(),
        )
        record = await recorder.record(
            UserId(1), "a" * 64, "astrbot", outcome,
        )
        assert record.final_state == "all_failed"
        assert record.selected_engine is None
        obs = record.observations[0]
        assert obs.result_status == "failed"
        assert obs.error_type == "timeout"
        assert obs.song_title is None

    async def test_records_circuit_rejected(self) -> None:
        repo = FakeOcrRunRepo()
        recorder = OcrRunRecorder(repo)
        rejected_id = EngineIdentity("z", "zhipu", "z")
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.DEGRADED_SINGLE,
            selected=_make_validated_strong(), consensus=None,
            results=(
                EngineResult(
                    identity=EngineIdentity("g", "google", "g"),
                    status=EngineResultStatus.SUCCESS,
                    observation=_obs(), validated=_make_validated_strong(),
                    error=None, elapsed_ms=100,
                ),
            ),
            circuit_rejects=(rejected_id,),
        )
        record = await recorder.record(
            UserId(1), "a" * 64, "astrbot", outcome,
        )
        assert len(record.observations) == 2
        rejected = [o for o in record.observations if o.result_status == "circuit_rejected"]
        assert len(rejected) == 1
        assert rejected[0].engine_id == "z"
        assert rejected[0].provider == "zhipu"
