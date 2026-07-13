"""Tests for OCR run domain types."""
from datetime import datetime, timezone

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


class TestOcrEngineRecord:
    def test_success_record(self) -> None:
        rec = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test Song", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
            matched_chart_id=1, validation_status="strong", error_type=None,
        )
        assert rec.engine_id == "g"
        assert rec.result_status == "success"
        assert rec.judgements is not None

    def test_error_record(self) -> None:
        rec = OcrEngineRecord(
            engine_id="g", provider="google", result_status="failed",
            elapsed_ms=5000, song_title=None, difficulty=None,
            displayed_level=None, judgements=None,
            matched_chart_id=None, validation_status=None,
            error_type="timeout",
        )
        assert rec.result_status == "failed"
        assert rec.error_type == "timeout"
        assert rec.song_title is None

    def test_circuit_rejected_record(self) -> None:
        rec = OcrEngineRecord(
            engine_id="z", provider="zhipu", result_status="circuit_rejected",
            elapsed_ms=0, song_title=None, difficulty=None,
            displayed_level=None, judgements=None,
            matched_chart_id=None, validation_status=None, error_type=None,
        )
        assert rec.result_status == "circuit_rejected"

    def test_frozen(self) -> None:
        rec = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="T", difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            matched_chart_id=1, validation_status="strong", error_type=None,
        )
        try:
            rec.engine_id = "x"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass


class TestOcrRunRecord:
    def test_record_creation(self) -> None:
        obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            matched_chart_id=1, validation_status="strong", error_type=None,
        )
        now = datetime.now(timezone.utc)
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="a" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(obs,), created_at=now,
        )
        assert record.id is None
        assert record.final_state == "consensus"
        assert len(record.observations) == 1

    def test_frozen(self) -> None:
        now = datetime.now(timezone.utc)
        record = OcrRunRecord(
            id=1, user_id=UserId(1),
            image_sha256="a" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine=None,
            observations=(), created_at=now,
        )
        try:
            record.final_state = "x"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass
