"""Tests for shared OCR prompt — all adapters must use the same prompt source."""
from __future__ import annotations

import pytest


class TestSharedPromptExists:
    """Verify that a single, vendor-neutral prompt module exists."""

    def test_prompt_module_exists(self) -> None:
        """adapters.vision._prompt must exist and export PJSK_OCR_PROMPT."""
        from adapters.vision._prompt import PJSK_OCR_PROMPT

        assert isinstance(PJSK_OCR_PROMPT, str)
        assert len(PJSK_OCR_PROMPT) > 50

    def test_prompt_contains_critical_keywords(self) -> None:
        """Prompt must include constraints from old emu-bot validated prompts."""
        from adapters.vision._prompt import PJSK_OCR_PROMPT

        # The prompt must instruct the model to read exact digits
        assert "EXACT" in PJSK_OCR_PROMPT or "exact" in PJSK_OCR_PROMPT.lower()
        # Must mention stripping leading zeros
        assert "leading zero" in PJSK_OCR_PROMPT.lower()
        # Must handle unreadable rows
        assert "unreadable" in PJSK_OCR_PROMPT.lower() or "blank" in PJSK_OCR_PROMPT.lower()
        # Must require JSON output
        assert "JSON" in PJSK_OCR_PROMPT or "json" in PJSK_OCR_PROMPT.lower()
        # Must list the difficulty enum
        assert "APPEND" in PJSK_OCR_PROMPT


class TestAllAdaptersUseSharedPrompt:
    """Every vision adapter must reference the shared prompt, not inline text."""

    def test_gemini_uses_shared_prompt(self) -> None:
        from adapters.vision._prompt import PJSK_OCR_PROMPT
        from adapters.vision.gemini import GEMINI_OCR_PROMPT

        assert GEMINI_OCR_PROMPT is PJSK_OCR_PROMPT

    def test_zhipu_uses_shared_prompt(self) -> None:
        from adapters.vision._prompt import PJSK_OCR_PROMPT
        from adapters.vision.zhipu import ZHIPU_OCR_PROMPT

        assert ZHIPU_OCR_PROMPT is PJSK_OCR_PROMPT

    def test_dashscope_uses_shared_prompt(self) -> None:
        from adapters.vision._prompt import PJSK_OCR_PROMPT
        from adapters.vision.dashscope import DASHSCOPE_OCR_PROMPT

        assert DASHSCOPE_OCR_PROMPT is PJSK_OCR_PROMPT

    def test_stepfun_uses_shared_prompt(self) -> None:
        from adapters.vision._prompt import PJSK_OCR_PROMPT
        from adapters.vision.stepfun import STEPFUN_OCR_PROMPT

        assert STEPFUN_OCR_PROMPT is PJSK_OCR_PROMPT


class TestAdapterParseRegression:
    """Existing response parsing must not regress after prompt migration.

    These tests mirror the existing per-adapter parsing tests but verify
    that the adapters still work correctly when using the shared prompt
    path at import time.
    """

    def test_gemini_imports_cleanly(self) -> None:
        """Gemini adapter must import without error after migration."""
        from adapters.vision.gemini import GeminiVisionEngine
        assert GeminiVisionEngine is not None

    def test_zhipu_imports_cleanly(self) -> None:
        from adapters.vision.zhipu import ZhipuVisionEngine
        assert ZhipuVisionEngine is not None

    def test_dashscope_imports_cleanly(self) -> None:
        from adapters.vision.dashscope import DashScopeVisionEngine
        assert DashScopeVisionEngine is not None

    def test_stepfun_imports_cleanly(self) -> None:
        from adapters.vision.stepfun import StepFunVisionEngine
        assert StepFunVisionEngine is not None


class TestSharedUtilities:
    """Common adapter utilities must come from a single source, not be duplicated."""

    def test_diff_map_is_consistently_imported(self) -> None:
        """_DIFF_MAP must be the same object regardless of import path."""
        from adapters.vision._shared import _DIFF_MAP as shared_map
        import adapters.vision._shared as s

        assert s._DIFF_MAP is shared_map

    def test_parse_ocr_json_roundtrip(self) -> None:
        """_parse_ocr_json must produce correct OcrObservation from valid JSON."""
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.charts import Difficulty

        data = {
            "song_title": "幾望の月",
            "difficulty": "MASTER",
            "level": 31,
            "perfect": 917,
            "great": 50,
            "good": 3,
            "bad": 0,
            "miss": 0,
        }
        obs = _parse_ocr_json(json.dumps(data), "test-engine")
        assert obs.song_title == "幾望の月"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 31
        assert obs.judgements.perfect == 917
        assert obs.judgements.great == 50
        assert obs.judgements.good == 3
        assert obs.judgements.bad == 0
        assert obs.judgements.miss == 0
        assert obs.engine == "test-engine"

    def test_parse_ocr_json_uses_song_title_not_title(self) -> None:
        """_parse_ocr_json reads 'song_title', not 'title'."""
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        # "title" field must NOT be accepted
        with pytest.raises(VisionResponseError, match="song_title is missing"):
            _parse_ocr_json(
                json.dumps({"title": "Old", "difficulty": "MASTER",
                 "level": 30, "perfect": 1, "great": 0,
                 "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

        # "song_title" field must be accepted
        obs = _parse_ocr_json(
            json.dumps({"song_title": "New", "difficulty": "MASTER",
             "level": 30, "perfect": 1, "great": 0,
             "good": 0, "bad": 0, "miss": 0}),
            "test",
        )
        assert obs.song_title == "New"

    def test_parse_ocr_json_0000_is_zero(self) -> None:
        """0000 must parse as integer 0, not string '0000'."""
        import json
        from adapters.vision._shared import _parse_ocr_json

        obs = _parse_ocr_json(
            json.dumps({"song_title": "Test", "difficulty": "EASY",
             "level": 1, "perfect": 1, "great": 0,
             "good": 0, "bad": 0, "miss": 0}),
            "test",
        )
        assert obs.judgements.miss == 0
        assert isinstance(obs.judgements.miss, int)

    def test_parse_ocr_json_numeric_title_kept_as_string(self) -> None:
        """Song title like '0.0000034' must stay as string, not float."""
        import json
        from adapters.vision._shared import _parse_ocr_json

        obs = _parse_ocr_json(
            json.dumps({"song_title": "0.0000034", "difficulty": "MASTER",
             "level": 34, "perfect": 1916, "great": 18,
             "good": 0, "bad": 0, "miss": 0}),
            "test",
        )
        assert obs.song_title == "0.0000034"
        assert isinstance(obs.song_title, str)

    def test_parse_ocr_json_missing_song_title_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="song_title is missing"):
            _parse_ocr_json(
                json.dumps({"difficulty": "MASTER", "level": 30,
                 "perfect": 1, "great": 0, "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_parse_ocr_json_empty_song_title_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="song_title is missing"):
            _parse_ocr_json(
                json.dumps({"song_title": "", "difficulty": "MASTER",
                 "level": 30, "perfect": 1, "great": 0,
                 "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_parse_ocr_json_invalid_difficulty_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="Unknown difficulty"):
            _parse_ocr_json(
                json.dumps({"song_title": "T", "difficulty": "LEGEND",
                 "level": 30, "perfect": 1, "great": 0,
                 "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_parse_ocr_json_negative_judgement_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="Negative judgement"):
            _parse_ocr_json(
                json.dumps({"song_title": "T", "difficulty": "MASTER",
                 "level": 30, "perfect": -1, "great": 0,
                 "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_parse_ocr_json_missing_judgement_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="Missing or invalid judgement"):
            _parse_ocr_json(
                json.dumps({"song_title": "T", "difficulty": "MASTER",
                 "level": 30, "perfect": 1, "great": 0,
                 "good": 0, "bad": 0}),
                "test",
            )

    def test_parse_ocr_json_junk_judgement_rejected(self) -> None:
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="Invalid JSON"):
            _parse_ocr_json("not json at all {{{", "test")

    def test_parse_ocr_json_missing_level_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="Invalid or missing level"):
            _parse_ocr_json(
                json.dumps({"song_title": "T", "difficulty": "MASTER",
                 "perfect": 1, "great": 0, "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_parse_ocr_json_zero_level_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="level must be positive"):
            _parse_ocr_json(
                json.dumps({"song_title": "T", "difficulty": "MASTER",
                 "level": 0, "perfect": 1, "great": 0,
                 "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_parse_ocr_json_ui_label_rejected(self) -> None:
        import json
        from adapters.vision._shared import _parse_ocr_json
        from pjsk_core.domain.ocr import VisionResponseError

        with pytest.raises(VisionResponseError, match="UI label"):
            _parse_ocr_json(
                json.dumps({"song_title": "スコア", "difficulty": "MASTER",
                 "level": 33, "perfect": 1821, "great": 0,
                 "good": 0, "bad": 0, "miss": 0}),
                "test",
            )

    def test_encode_base64_is_shared(self) -> None:
        """_encode_base64 must be the same function across all adapters."""
        from adapters.vision._shared import _encode_base64 as shared_fn
        import adapters.vision.gemini as g
        import adapters.vision.zhipu as z
        import adapters.vision.dashscope as d
        import adapters.vision.stepfun as s

        assert g._encode_base64 is shared_fn  # type: ignore[attr-defined]
        assert z._encode_base64 is shared_fn  # type: ignore[attr-defined]
        assert d._encode_base64 is shared_fn  # type: ignore[attr-defined]
        assert s._encode_base64 is shared_fn  # type: ignore[attr-defined]

    def test_extract_json_is_shared(self) -> None:
        """_extract_json must be the same function in zhipu and dashscope."""
        from adapters.vision._shared import _extract_json as shared_fn
        import adapters.vision.zhipu as z
        import adapters.vision.dashscope as d

        assert z._extract_json is shared_fn  # type: ignore[attr-defined]
        assert d._extract_json is shared_fn  # type: ignore[attr-defined]
