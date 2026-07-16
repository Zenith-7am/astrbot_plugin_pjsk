"""Tests for GeminiVisionEngine response parsing (no real HTTP calls)."""
from __future__ import annotations

import json
import pytest

from adapters.vision.gemini import GeminiVisionEngine
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity, VisionResponseError


class TestGeminiResponseParsing:
    def test_parses_valid_json_response(self) -> None:
        """_parse_response should extract all fields from a valid Gemini API response."""
        engine = object.__new__(GeminiVisionEngine)
        engine._model = "gemini-2.5-flash"
        engine.identity = EngineIdentity(
            "gemini-gemini-2.5-flash",
            "google",
            "gemini-2.5-flash",
        )

        fake_api_response = {
            "candidates": [{
                "content": {"parts": [{
                    "text": json.dumps({
                        "title": "Test Song",
                        "difficulty": "MASTER",
                        "level": 30,
                        "perfect": 1000,
                        "great": 100,
                        "good": 0,
                        "bad": 0,
                        "miss": 0,
                    })
                }]}
            }]
        }
        obs = engine._parse_response(fake_api_response)
        assert obs.song_title == "Test Song"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 30
        assert obs.judgements.perfect == 1000

    def test_invalid_difficulty_raises(self) -> None:
        """A difficulty string not in the known mapping should raise VisionResponseError."""
        engine = object.__new__(GeminiVisionEngine)
        engine._model = "g"
        engine.identity = EngineIdentity("g", "google", "g")
        fake = {
            "candidates": [{"content": {"parts": [{
                "text": json.dumps({
                    "song_title": "T", "difficulty": "LEGEND",
                    "level": 30, "perfect": 1, "great": 0,
                    "good": 0, "bad": 0, "miss": 0,
                })
            }]}}]
        }
        with pytest.raises(VisionResponseError, match="Unknown difficulty"):
            engine._parse_response(fake)

    def test_secret_not_in_repr(self) -> None:
        """Secret must not leak the value in repr()."""
        from adapters.vision.gemini import Secret
        s = Secret("sk-abc123")
        assert "sk-abc123" not in repr(s)
        assert s.reveal() == "sk-abc123"
