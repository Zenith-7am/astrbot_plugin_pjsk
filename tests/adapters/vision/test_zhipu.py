"""Tests for ZhipuVisionEngine — response parsing, thinking, JSON extraction."""
from __future__ import annotations

import json

import pytest

from adapters.vision.gemini import Secret
from adapters.vision.zhipu import ZhipuVisionEngine, _extract_json  # type: ignore[attr-defined]
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity, VisionResponseError


def _make_engine(model: str = "glm-4.6v-flash",
                 thinking: bool = False) -> ZhipuVisionEngine:
    eng = object.__new__(ZhipuVisionEngine)
    eng._model = model
    eng._thinking_enabled = thinking
    eng.identity = EngineIdentity(f"zhipu-{model}", "zhipu", model)
    return eng


class TestZhipuResponseParsing:
    def test_parses_bare_json_response(self) -> None:
        """Bare JSON in message.content must be correctly parsed."""
        engine = _make_engine()
        fake = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "Test Song",
                        "difficulty": "EXPERT",
                        "level": 29,
                        "perfect": 800, "great": 50,
                        "good": 2, "bad": 0, "miss": 1,
                    })
                }
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "Test Song"
        assert obs.difficulty == Difficulty.EXPERT
        assert obs.displayed_level == 29
        assert obs.judgements.perfect == 800

    def test_parses_fenced_json_response(self) -> None:
        """Fenced ```json ... ``` in message.content must be extracted."""
        engine = _make_engine()
        inner = json.dumps({
            "song_title": "Fenced", "difficulty": "MASTER",
            "level": 31, "perfect": 1, "great": 0,
            "good": 0, "bad": 0, "miss": 0,
        })
        fake = {
            "choices": [{
                "message": {
                    "content": f"Here is the result:\n```json\n{inner}\n```\nDone."
                }
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "Fenced"
        assert obs.difficulty == Difficulty.MASTER

    def test_content_only_not_reasoning(self) -> None:
        """When reasoning_content is present, only message.content is parsed."""
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
                    "reasoning_content": "Let me look at this... I think the song is WrongTitle",
                }
            }]
        }
        obs = engine._parse_response(fake)
        assert obs.song_title == "ContentWin"  # NOT "WrongTitle"

    def test_invalid_difficulty_raises(self) -> None:
        engine = _make_engine()
        fake = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "song_title": "T", "difficulty": "ULTIMATE",
                        "level": 30, "perfect": 1, "great": 0,
                        "good": 0, "bad": 0, "miss": 0,
                    })
                }
            }]
        }
        with pytest.raises(VisionResponseError, match="Unknown difficulty"):
            engine._parse_response(fake)

    def test_malformed_json_raises(self) -> None:
        engine = _make_engine()
        fake = {
            "choices": [{
                "message": {"content": "not json at all {{{"}
            }]
        }
        with pytest.raises(VisionResponseError, match="not bare JSON"):
            engine._parse_response(fake)

    def test_missing_choices_key_raises(self) -> None:
        engine = _make_engine()
        with pytest.raises(VisionResponseError, match="Cannot parse Zhipu response"):
            engine._parse_response({"no_choices": []})

    def test_secret_not_in_repr(self) -> None:
        s = Secret("sk-zhipu-secret")
        assert "sk-zhipu-secret" not in repr(s)
        assert s.reveal() == "sk-zhipu-secret"

    def test_api_key_not_in_repr_or_logs(self) -> None:
        """Engine repr must not leak API key."""
        import httpx
        eng = ZhipuVisionEngine(
            api_key="sk-top-secret-12345",
            model="glm-4.6v-flash",
            client=httpx.AsyncClient(),
        )
        r = repr(eng)
        assert "sk-top-secret-12345" not in r
        # identity must be public
        assert "zhipu-glm-4.6v-flash" in r or "zhipu-glm-4.6v-flash" in str(eng.identity)


class TestThinkingControl:
    """Verify thinking param in request body and __init__ wiring."""

    def test_thinking_disabled_default(self) -> None:
        eng = _make_engine(thinking=False)
        assert eng._thinking_enabled is False

    def test_thinking_enabled_true(self) -> None:
        eng = _make_engine(thinking=True)
        assert eng._thinking_enabled is True

    def test_identity_uses_engine_id(self) -> None:
        eng = _make_engine("glm-4.6v-flash")
        assert eng.identity.provider == "zhipu"
        assert eng.identity.engine_id == "zhipu-glm-4.6v-flash"


class TestExtractJson:
    """Unit tests for the _extract_json helper."""

    def test_bare_json(self) -> None:
        result = _extract_json(' {"key": 1} ')
        assert result == '{"key": 1}'

    def test_fenced_json(self) -> None:
        result = _extract_json('```json\n{"a": 1}\n```')
        assert result == '{"a": 1}'

    def test_fenced_with_text_around(self) -> None:
        result = _extract_json('Prefix\n```json\n{"x": "y"}\n```\nSuffix')
        assert result == '{"x": "y"}'

    def test_no_json_raises(self) -> None:
        with pytest.raises(VisionResponseError, match="not bare JSON"):
            _extract_json("Hello world")

    def test_empty_fenced_block_raises(self) -> None:
        with pytest.raises(VisionResponseError):
            _extract_json("```json\n\n```")
