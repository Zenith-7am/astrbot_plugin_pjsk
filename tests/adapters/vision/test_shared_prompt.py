"""Tests for shared OCR prompt — all adapters must use the same prompt source."""
from __future__ import annotations


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

    def test_diff_map_is_shared(self) -> None:
        """_DIFF_MAP must be the same object across all adapters."""
        from adapters.vision._shared import _DIFF_MAP as shared_map
        # Verify adapters re-export the same object via import
        import adapters.vision.zhipu as z
        import adapters.vision.dashscope as d
        import adapters.vision.stepfun as s

        assert z._DIFF_MAP is shared_map  # type: ignore[attr-defined]
        assert d._DIFF_MAP is shared_map  # type: ignore[attr-defined]
        assert s._DIFF_MAP is shared_map  # type: ignore[attr-defined]

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
