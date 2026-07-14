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
