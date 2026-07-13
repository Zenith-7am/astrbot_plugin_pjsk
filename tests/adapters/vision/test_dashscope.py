"""Tests for DashScopeVisionEngine — OpenAI-compatible parser, mock HTTP only."""
from __future__ import annotations

import json

import pytest

from adapters.vision.dashscope import DashScopeVisionEngine
from adapters.vision.gemini import Secret
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity, VisionResponseError


def _make_engine(model: str = "qwen3-vl-flash",
                 thinking: bool = False) -> DashScopeVisionEngine:
    eng = object.__new__(DashScopeVisionEngine)
    eng._model = model
    eng._thinking_enabled = thinking
    eng.identity = EngineIdentity(f"dashscope-{model}", "dashscope", model)
    return eng


class TestDashScopeResponseParsing:
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
            "song_title": "Fenced", "difficulty": "EXPERT",
            "level": 29, "perfect": 1, "great": 0,
            "good": 0, "bad": 0, "miss": 0,
        })
        fake = {
            "choices": [{
                "message": {"content": f"```json\n{inner}\n```"}
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "Fenced"

    def test_content_only_not_reasoning(self) -> None:
        engine = _make_engine(thinking=True)
        inner = json.dumps({
            "song_title": "ContentWin", "difficulty": "HARD",
            "level": 20, "perfect": 1, "great": 0,
            "good": 0, "bad": 0, "miss": 0,
        })
        fake = {
            "choices": [{
                "message": {
                    "content": inner,
                    "reasoning_content": "I think it's WrongTitle",
                }
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "ContentWin"

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
        fake = {"choices": [{"message": {"content": "not json"}}]}
        with pytest.raises(VisionResponseError, match="not bare JSON"):
            engine._parse_response(fake)


class TestDashScopeIdentity:
    def test_provider_is_dashscope(self) -> None:
        eng = _make_engine("qwen3-vl-flash")
        assert eng.identity.provider == "dashscope"
        assert eng.identity.engine_id == "dashscope-qwen3-vl-flash"

    def test_api_key_not_in_repr(self) -> None:
        import httpx
        eng = DashScopeVisionEngine(
            api_key="sk-dashscope-secret",
            model="qwen3-vl-flash",
            client=httpx.AsyncClient(),
        )
        r = repr(eng)
        assert "sk-dashscope-secret" not in r
        assert "dashscope" in repr(eng.identity)

    def test_secret_not_in_repr(self) -> None:
        s = Secret("sk-dash")
        assert "sk-dash" not in repr(s)
        assert s.reveal() == "sk-dash"

    def test_thinking_disabled_default(self) -> None:
        eng = _make_engine(thinking=False)
        assert eng._thinking_enabled is False

    def test_thinking_enabled_true(self) -> None:
        eng = _make_engine(thinking=True)
        assert eng._thinking_enabled is True
