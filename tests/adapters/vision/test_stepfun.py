"""Tests for StepFunVisionEngine response parsing (no real HTTP calls)."""
from __future__ import annotations

import json

import pytest

from adapters.vision.gemini import Secret
from adapters.vision.stepfun import StepFunVisionEngine
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity, VisionResponseError


class TestStepFunResponseParsing:
    def test_parses_valid_json_response(self) -> None:
        """_parse_response should extract all fields from a valid StepFun API response."""
        engine = object.__new__(StepFunVisionEngine)
        engine._model = "step-1v-32k"
        engine.identity = EngineIdentity(
            "stepfun-step-1v-32k",
            "stepfun",
            "step-1v-32k",
        )

        fake_api_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "Step Song",
                        "difficulty": "MASTER",
                        "level": 31,
                        "perfect": 1200,
                        "great": 30,
                        "good": 0,
                        "bad": 0,
                        "miss": 0,
                    })
                }
            }]
        }
        obs = engine._parse_response(fake_api_response)
        assert obs.song_title == "Step Song"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 31
        assert obs.judgements.perfect == 1200
        assert obs.judgements.great == 30
        assert obs.judgements.good == 0
        assert obs.judgements.bad == 0
        assert obs.judgements.miss == 0
        assert obs.engine == "stepfun-step-1v-32k"

    def test_invalid_difficulty_raises(self) -> None:
        """A difficulty string not in the known mapping should raise VisionResponseError."""
        engine = object.__new__(StepFunVisionEngine)
        engine._model = "v"
        engine.identity = EngineIdentity("s-v", "stepfun", "v")
        fake = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "T",
                        "difficulty": "LEGEND",
                        "level": 30,
                        "perfect": 1,
                        "great": 0,
                        "good": 0,
                        "bad": 0,
                        "miss": 0,
                    })
                }
            }]
        }
        with pytest.raises(VisionResponseError, match="Unknown difficulty"):
            engine._parse_response(fake)

    def test_missing_choices_key_raises(self) -> None:
        """Missing 'choices' key should raise VisionResponseError."""
        engine = object.__new__(StepFunVisionEngine)
        engine._model = "v"
        engine.identity = EngineIdentity("s-v", "stepfun", "v")
        with pytest.raises(VisionResponseError, match="Cannot parse StepFun response"):
            engine._parse_response({"no_choices": []})

    def test_secret_not_in_repr(self) -> None:
        """Secret must not leak the value in repr()."""
        s = Secret("sk-stepfun-secret")
        assert "sk-stepfun-secret" not in repr(s)
        assert s.reveal() == "sk-stepfun-secret"
