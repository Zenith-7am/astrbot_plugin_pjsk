"""Tests for pjsk_core.domain.ocr — vision engine observation type."""

import pytest

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements


class TestOcrObservation:
    def test_valid_observation(self) -> None:
        obs = OcrObservation(
            song_title="Tell Your World",
            difficulty=Difficulty.MASTER,
            displayed_level=31,
            judgements=Judgements(perfect=1000, great=10, good=0, bad=0, miss=0),
            engine="gemini",
            elapsed_ms=1234,
        )
        assert obs.song_title == "Tell Your World"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 31
        assert obs.judgements.perfect == 1000
        assert obs.engine == "gemini"
        assert obs.elapsed_ms == 1234

    def test_frozen(self) -> None:
        obs = OcrObservation(
            song_title="Test",
            difficulty=Difficulty.EASY,
            displayed_level=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            engine="test",
            elapsed_ms=0,
        )
        with pytest.raises(Exception):
            obs.song_title = "Changed"  # type: ignore[misc]
