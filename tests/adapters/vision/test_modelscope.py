"""Tests for ModelScopeVisionEngine — OpenAI-compatible parser, no real HTTP."""
from __future__ import annotations

import json

import pytest

from adapters.vision.gemini import Secret
from adapters.vision.modelscope import ModelScopeVisionEngine, _extract_json
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity, VisionResponseError


def _make_engine(model: str = "Qwen/QVQ-72B-Preview") -> ModelScopeVisionEngine:
    eng = object.__new__(ModelScopeVisionEngine)
    eng._model = model
    eng.identity = EngineIdentity(f"modelscope-{model}", "modelscope", model)
    return eng


class TestModelScopeResponseParsing:
    def test_parses_bare_json(self) -> None:
        engine = _make_engine()
        fake = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "Song", "difficulty": "MASTER",
                        "level": 31, "perfect": 1, "great": 0,
                        "good": 0, "bad": 0, "miss": 0,
                    })
                }
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "Song"
        assert obs.difficulty == Difficulty.MASTER

    def test_parses_fenced_json(self) -> None:
        engine = _make_engine()
        inner = json.dumps({
            "song_title": "FencedSong", "difficulty": "EXPERT",
            "level": 29, "perfect": 1, "great": 0,
            "good": 0, "bad": 0, "miss": 0,
        })
        fake = {
            "choices": [{
                "message": {
                    "content": f"```json\n{inner}\n```"
                }
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "FencedSong"

    def test_invalid_difficulty_raises(self) -> None:
        engine = _make_engine()
        fake = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "X", "difficulty": "INVALID",
                        "level": 1, "perfect": 1, "great": 0,
                        "good": 0, "bad": 0, "miss": 0,
                    })
                }
            }]
        }
        with pytest.raises(VisionResponseError, match="Unknown difficulty"):
            engine._parse_response(fake)

    def test_missing_choices_raises(self) -> None:
        engine = _make_engine()
        with pytest.raises(VisionResponseError, match="Cannot parse"):
            engine._parse_response({"wrong": []})

    def test_malformed_json_raises(self) -> None:
        engine = _make_engine()
        fake = {"choices": [{"message": {"content": "not json!!!"}}]}
        with pytest.raises(VisionResponseError, match="not bare JSON"):
            engine._parse_response(fake)


class TestModelScopeIdentity:
    def test_engine_id_contains_platform_and_model(self) -> None:
        eng = _make_engine("Qwen/QVQ-72B-Preview")
        assert eng.identity.provider == "modelscope"
        assert eng.identity.engine_id == "modelscope-Qwen/QVQ-72B-Preview"

    def test_api_key_not_in_repr(self) -> None:
        import httpx
        eng = ModelScopeVisionEngine(
            api_key="ms-secret-key-12345",
            model="Qwen/QVQ-72B-Preview",
            client=httpx.AsyncClient(),
        )
        r = repr(eng)
        assert "ms-secret-key-12345" not in r
        assert "modelscope" in repr(eng.identity)

    def test_secret_not_in_repr(self) -> None:
        s = Secret("ms-secret")
        assert "ms-secret" not in repr(s)
        assert s.reveal() == "ms-secret"


class TestExtractJson:
    def test_bare_json(self) -> None:
        assert _extract_json(' {"a":1} ') == '{"a":1}'

    def test_fenced_json(self) -> None:
        assert _extract_json('```json\n{"x":1}\n```') == '{"x":1}'

    def test_no_json_raises(self) -> None:
        with pytest.raises(VisionResponseError, match="not bare JSON"):
            _extract_json("Hello")
