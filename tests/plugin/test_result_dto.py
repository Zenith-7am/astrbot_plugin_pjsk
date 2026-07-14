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
