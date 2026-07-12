"""Tests for ZhipuVisionEngine response parsing (no real HTTP calls)."""
from __future__ import annotations

import json

import pytest

from adapters.vision.gemini import Secret
from adapters.vision.zhipu import ZhipuVisionEngine
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity, VisionResponseError


class TestZhipuResponseParsing:
    def test_parses_valid_json_response(self) -> None:
        """_parse_response should extract all fields from a valid Zhipu API response."""
        engine = object.__new__(ZhipuVisionEngine)
        engine._model = "glm-4v-plus"
        engine.identity = EngineIdentity(
            "zhipu-glm-4v-plus",
            "zhipu",
            "glm-4v-plus",
        )

        fake_api_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "Test Song",
                        "difficulty": "EXPERT",
                        "level": 29,
                        "perfect": 800,
                        "great": 50,
                        "good": 2,
                        "bad": 0,
                        "miss": 1,
                    })
                }
            }]
        }
        obs = engine._parse_response(fake_api_response)
        assert obs.song_title == "Test Song"
        assert obs.difficulty == Difficulty.EXPERT
        assert obs.displayed_level == 29
        assert obs.judgements.perfect == 800
        assert obs.judgements.great == 50
        assert obs.judgements.good == 2
        assert obs.judgements.bad == 0
        assert obs.judgements.miss == 1
        assert obs.engine == "zhipu-glm-4v-plus"

    def test_invalid_difficulty_raises(self) -> None:
        """A difficulty string not in the known mapping should raise VisionResponseError."""
        engine = object.__new__(ZhipuVisionEngine)
        engine._model = "v"
        engine.identity = EngineIdentity("z-v", "zhipu", "v")
        fake = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "T",
                        "difficulty": "ULTIMATE",
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
        engine = object.__new__(ZhipuVisionEngine)
        engine._model = "v"
        engine.identity = EngineIdentity("z-v", "zhipu", "v")
        with pytest.raises(VisionResponseError, match="Cannot parse Zhipu response"):
            engine._parse_response({"no_choices": []})

    def test_secret_not_in_repr(self) -> None:
        """Secret must not leak the value in repr()."""
        s = Secret("sk-zhipu-secret")
        assert "sk-zhipu-secret" not in repr(s)
        assert s.reveal() == "sk-zhipu-secret"
