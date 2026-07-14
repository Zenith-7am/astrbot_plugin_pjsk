"""Tests for ScoreEcho result DTO and format_score_echo."""
from __future__ import annotations

import pytest

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import ScoreStatus


class TestScoreEcho:
    """ScoreEcho dataclass carries echo-ready fields from OCR result."""

    def test_echo_holds_all_fields(self) -> None:
        from pjsk_emubot.result_dto import ScoreEcho

        echo = ScoreEcho(
            song_title="幾望の月",
            difficulty=Difficulty.MASTER,
            displayed_level=31,
            status=ScoreStatus.FC,
            accuracy=99.83,
            rating=33.12,
            decision_source="多模型共识",
        )
        assert echo.song_title == "幾望の月"
        assert echo.difficulty == Difficulty.MASTER
        assert echo.displayed_level == 31
        assert echo.status == ScoreStatus.FC
        assert echo.accuracy == 99.83
        assert echo.rating == 33.12
        assert echo.decision_source == "多模型共识"

    def test_echo_is_immutable(self) -> None:
        from pjsk_emubot.result_dto import ScoreEcho

        echo = ScoreEcho(
            song_title="Test", difficulty=Difficulty.HARD,
            displayed_level=20, status=ScoreStatus.CLEAR,
            accuracy=95.0, rating=22.0, decision_source="单模型强校验降级",
        )
        with pytest.raises(Exception):
            echo.accuracy = 100.0  # type: ignore[misc]


class TestDecisionSourceText:
    """Decision source text must be Chinese, not English enum values."""

    def test_consensus_text(self) -> None:
        from pjsk_emubot.result_dto import decision_source_text
        from pjsk_core.application.vision_race import VisionRaceDecision

        assert decision_source_text(VisionRaceDecision.CONSENSUS) == "多模型共识"

    def test_degraded_single_text(self) -> None:
        from pjsk_emubot.result_dto import decision_source_text
        from pjsk_core.application.vision_race import VisionRaceDecision

        assert decision_source_text(VisionRaceDecision.DEGRADED_SINGLE) == "单模型强校验降级"

    def test_global_timeout_text(self) -> None:
        from pjsk_emubot.result_dto import decision_source_text
        from pjsk_core.application.vision_race import VisionRaceDecision

        assert decision_source_text(VisionRaceDecision.GLOBAL_TIMEOUT) == "超时后强校验降级"

    def test_unknown_decision_returns_generic(self) -> None:
        from pjsk_emubot.result_dto import decision_source_text
        from pjsk_core.application.vision_race import VisionRaceDecision

        # ALL_FAILED, DISAGREEMENT, NO_AVAILABLE_ENGINES — not used for echo
        for dec in (VisionRaceDecision.ALL_FAILED,
                     VisionRaceDecision.DISAGREEMENT,
                     VisionRaceDecision.NO_AVAILABLE_ENGINES):
            # Should not crash — returns something
            text = decision_source_text(dec)
            assert isinstance(text, str)
            assert len(text) > 0


class TestFormatScoreEcho:
    """format_score_echo must produce the agreed display format."""

    def test_full_consensus_echo(self) -> None:
        from pjsk_emubot.result_dto import ScoreEcho, format_score_echo

        echo = ScoreEcho(
            song_title="幾望の月",
            difficulty=Difficulty.MASTER,
            displayed_level=31,
            status=ScoreStatus.FC,
            accuracy=99.83,
            rating=33.12,
            decision_source="多模型共识",
        )
        result = format_score_echo(echo)
        assert "已记录" in result
        assert "幾望の月" in result
        assert "MASTER 31" in result
        assert "FC" in result
        assert "99.83%" in result
        assert "33.12" in result
        assert "多模型共识" in result

    def test_ap_echo(self) -> None:
        from pjsk_emubot.result_dto import ScoreEcho, format_score_echo

        echo = ScoreEcho(
            song_title="Tell Your World",
            difficulty=Difficulty.EXPERT,
            displayed_level=26,
            status=ScoreStatus.AP,
            accuracy=101.00,
            rating=28.50,
            decision_source="多模型共识",
        )
        result = format_score_echo(echo)
        assert "已记录" in result
        assert "Tell Your World" in result
        assert "EXPERT 26" in result
        assert "AP" in result
        assert "101.00%" in result

    def test_degraded_single_echo(self) -> None:
        from pjsk_emubot.result_dto import ScoreEcho, format_score_echo

        echo = ScoreEcho(
            song_title="初音ミクの消失",
            difficulty=Difficulty.MASTER,
            displayed_level=35,
            status=ScoreStatus.CLEAR,
            accuracy=78.50,
            rating=20.30,
            decision_source="单模型强校验降级",
        )
        result = format_score_echo(echo)
        assert "CLEAR" in result
        assert "78.50%" in result
        assert "单模型强校验降级" in result

    def test_accuracy_formatting_precision(self) -> None:
        """Accuracy must be formatted to 2 decimal places."""
        from pjsk_emubot.result_dto import ScoreEcho, format_score_echo

        echo = ScoreEcho(
            song_title="Test", difficulty=Difficulty.HARD,
            displayed_level=15, status=ScoreStatus.CLEAR,
            accuracy=95.0, rating=18.0, decision_source="多模型共识",
        )
        result = format_score_echo(echo)
        assert "95.00%" in result

    def test_rating_formatting_precision(self) -> None:
        """Rating must be formatted to 2 decimal places."""
        from pjsk_emubot.result_dto import ScoreEcho, format_score_echo

        echo = ScoreEcho(
            song_title="Test", difficulty=Difficulty.HARD,
            displayed_level=15, status=ScoreStatus.CLEAR,
            accuracy=95.0, rating=18.0, decision_source="多模型共识",
        )
        result = format_score_echo(echo)
        assert "18.00" in result


class TestBuildScoreEcho:
    """build_score_echo must map RecognizeResult → ScoreEcho safely."""

    def test_consensus_result_returns_echo(self) -> None:
        """A CONSENSUS result with score_attempt must produce a ScoreEcho."""
        from datetime import datetime, timezone

        from pjsk_core.application.recognize_score import RecognizeResult
        from pjsk_core.application.vision_race import (
            VisionRaceDecision,
            VisionRaceOutcome,
        )
        from pjsk_core.application.validate_ocr import ValidatedObservation
        from pjsk_core.domain.ocr import OcrObservation
        from pjsk_core.domain.scores import Judgements, ScoreAttempt
        from pjsk_core.domain.users import UserId
        from pjsk_emubot.result_dto import build_score_echo

        obs = OcrObservation(
            song_title="幾望の月", difficulty=Difficulty.MASTER,
            displayed_level=31,
            judgements=Judgements(perfect=917, great=50, good=3, bad=0, miss=0),
            engine="gemini-gemini-2.5-flash", elapsed_ms=1200,
        )
        validated = ValidatedObservation(
            observation=obs, primary=None, candidates=(),
            status="STRONG",  # type: ignore[arg-type]
        )
        attempt = ScoreAttempt(
            id=1, user_id=UserId(1), chart_id=42,
            judgements=obs.judgements, accuracy=99.83, rating=33.12,
            status=ScoreStatus.FC, image_sha256="abc",
            source_gateway="onebot", ocr_run_id=1,
            created_at=datetime.now(timezone.utc),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.CONSENSUS,
            selected=validated, consensus=None,
            results=(), circuit_rejects=(),
        )
        result = RecognizeResult(
            outcome=outcome, validated=validated,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=attempt,
        )

        echo = build_score_echo(result)
        assert echo is not None
        assert echo.song_title == "幾望の月"
        assert echo.difficulty == Difficulty.MASTER
        assert echo.displayed_level == 31
        assert echo.status == ScoreStatus.FC
        assert echo.accuracy == 99.83
        assert echo.rating == 33.12
        assert echo.decision_source == "多模型共识"

    def test_no_score_attempt_returns_none(self) -> None:
        """When there's no score_attempt, build_score_echo returns None."""
        from pjsk_core.application.recognize_score import RecognizeResult
        from pjsk_core.application.vision_race import (
            VisionRaceDecision,
            VisionRaceOutcome,
        )
        from pjsk_emubot.result_dto import build_score_echo

        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.ALL_FAILED,
            selected=None, consensus=None,
            results=(), circuit_rejects=(),
        )
        result = RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=None,
        )
        assert build_score_echo(result) is None

    def test_missing_validated_returns_none(self) -> None:
        """Even with score_attempt, missing validated → None (defensive)."""
        from datetime import datetime, timezone

        from pjsk_core.application.recognize_score import RecognizeResult
        from pjsk_core.application.vision_race import (
            VisionRaceDecision,
            VisionRaceOutcome,
        )
        from pjsk_core.domain.scores import Judgements, ScoreAttempt
        from pjsk_core.domain.users import UserId
        from pjsk_emubot.result_dto import build_score_echo

        attempt = ScoreAttempt(
            id=1, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=35.0, status=ScoreStatus.AP,
            image_sha256="x", source_gateway="x", ocr_run_id=1,
            created_at=datetime.now(timezone.utc),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.CONSENSUS,
            selected=None, consensus=None,
            results=(), circuit_rejects=(),
        )
        result = RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=attempt,
        )
        assert build_score_echo(result) is None


class TestFormatConfirmEcho:
    """format_confirm_echo must produce compact confirm echo from ScoreAttempt."""

    def test_fc_confirm_echo(self) -> None:
        from datetime import datetime, timezone

        from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
        from pjsk_core.domain.users import UserId
        from pjsk_emubot.result_dto import format_confirm_echo

        attempt = ScoreAttempt(
            id=1, user_id=UserId(1), chart_id=42,
            judgements=Judgements(perfect=917, great=50, good=0, bad=0, miss=0),
            accuracy=99.83, rating=33.12, status=ScoreStatus.FC,
            image_sha256="x", source_gateway="x", ocr_run_id=1,
            created_at=datetime.now(timezone.utc),
        )
        result = format_confirm_echo(attempt)
        assert "已确认成绩" in result
        assert "FC" in result
        assert "99.83%" in result
        assert "33.12" in result
        assert "·" in result

    def test_ap_confirm_echo(self) -> None:
        from datetime import datetime, timezone

        from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
        from pjsk_core.domain.users import UserId
        from pjsk_emubot.result_dto import format_confirm_echo

        attempt = ScoreAttempt(
            id=2, user_id=UserId(1), chart_id=10,
            judgements=Judgements(perfect=1200, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=35.0, status=ScoreStatus.AP,
            image_sha256="y", source_gateway="y", ocr_run_id=2,
            created_at=datetime.now(timezone.utc),
        )
        result = format_confirm_echo(attempt)
        assert "已确认成绩" in result
        assert "AP" in result
        assert "101.00%" in result

    def test_none_returns_generic(self) -> None:
        from pjsk_emubot.result_dto import format_confirm_echo

        assert format_confirm_echo(None) == "已确认成绩"
