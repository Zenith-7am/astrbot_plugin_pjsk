"""Tests for Gemini JSON response mode (controlled generation).

Gemini API supports ``responseMimeType: "application/json"`` with an
optional ``responseSchema`` — this forces the model to output valid JSON
matching the schema, rather than relying on prompt text alone.
"""
from __future__ import annotations

import json


class TestGeminiJsonResponseMode:
    """Gemini adapter must enable JSON response mode in the request body."""

    def test_request_body_includes_generation_config(self) -> None:
        """_build_request_body must include generationConfig section."""
        from adapters.vision.gemini import _build_request_body

        body = _build_request_body(b"fake-image", "test prompt")
        assert "generationConfig" in body

    def test_response_mime_type_is_json(self) -> None:
        """generationConfig.responseMimeType must be application/json."""
        from adapters.vision.gemini import _build_request_body

        body = _build_request_body(b"fake-image", "test prompt")
        assert body["generationConfig"]["responseMimeType"] == "application/json"

    def test_response_schema_has_expected_properties(self) -> None:
        """responseSchema must describe the fields our parser expects."""
        from adapters.vision.gemini import _build_request_body

        body = _build_request_body(b"fake-image", "test prompt")
        schema = body["generationConfig"]["responseSchema"]
        assert schema["type"] == "OBJECT"
        props = schema["properties"]
        assert "song_title" in props
        assert props["song_title"]["type"] == "STRING"
        assert "difficulty" in props
        assert "level" in props
        assert props["level"]["type"] == "INTEGER"
        for key in ("perfect", "great", "good", "bad", "miss"):
            assert key in props
            assert props[key]["type"] == "INTEGER"

    def test_response_schema_required_fields(self) -> None:
        """All fields must be listed as required."""
        from adapters.vision.gemini import _build_request_body

        body = _build_request_body(b"fake-image", "test prompt")
        required = body["generationConfig"]["responseSchema"]["required"]
        assert "song_title" in required
        assert "difficulty" in required
        assert "level" in required
        for key in ("perfect", "great", "good", "bad", "miss"):
            assert key in required


class TestJsonModeParseCompatibility:
    """Response parsing must stay compatible with JSON-mode responses.

    JSON mode guarantees ``parts[0].text`` is valid JSON — the existing
    ``_parse_response`` already does ``json.loads(text)``, so it should
    be transparently compatible.
    """

    def test_parse_json_mode_response(self) -> None:
        """_parse_response must handle a JSON-mode response correctly."""
        from adapters.vision.gemini import GeminiVisionEngine
        from pjsk_core.domain.charts import Difficulty
        from pjsk_core.domain.ocr import EngineIdentity

        engine = object.__new__(GeminiVisionEngine)
        engine._model = "gemini-2.5-flash"
        engine.identity = EngineIdentity(
            "gemini-gemini-2.5-flash", "google", "gemini-2.5-flash",
        )

        # JSON mode guarantees content is valid JSON — same format
        # our parser expects, just without any markdown wrapping.
        fake = {
            "candidates": [{
                "content": {"parts": [{
                    "text": json.dumps({
                        "song_title": "幾望の月",
                        "difficulty": "MASTER",
                        "level": 31,
                        "perfect": 917,
                        "great": 50,
                        "good": 3,
                        "bad": 0,
                        "miss": 0,
                    })
                }]}
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "幾望の月"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 31
        assert obs.judgements.perfect == 917
        assert obs.judgements.great == 50
