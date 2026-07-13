"""Smoke tests for the Composition Root."""
import os
from pathlib import Path

import pytest
from pjsk_emubot.bootstrap import _resolve_db_path, assemble_plugin_runtime


@pytest.fixture(autouse=True)
def _vision_env() -> None:
    """Set dummy API keys so at least one vision engine is created.

    The engine constructors do NOT make network calls — they only store
    the arguments.  In CI, set these to any non-empty string.
    """
    os.environ.setdefault("GEMINI_API_KEY", "test-key")
    os.environ.setdefault("ZHIPU_API_KEY", "test-key")
    os.environ.setdefault("STEPFUN_API_KEY", "test-key")


class TestBootstrap:
    async def test_assemble_returns_runtime(self) -> None:
        """Smoke test: assembly completes without error."""
        rt = await assemble_plugin_runtime()
        assert rt is not None
        assert rt.user_repo is not None
        assert rt.recognize_score is not None
        assert rt.confirm_candidate is not None
        assert rt.candidate_store is not None
        assert rt.image_buffer is not None
        await rt.close()

    async def test_assemble_with_config_override(self) -> None:
        """Assembly with explicit config dict overrides."""
        config = {
            "gemini_api_key": "cfg-key",
            "ocr_timeout_seconds": 20,
            "candidate_ttl_seconds": 120,
            "user_cooldown_seconds": 3,
            "image_window_seconds": 10,
        }
        rt = await assemble_plugin_runtime(config)
        assert rt is not None
        await rt.close()

    async def test_assemble_no_engines_configured(self) -> None:
        """Assembly succeeds even with zero vision engines configured."""
        # Remove env vars so no engines are created
        for k in ("GEMINI_API_KEY", "ZHIPU_API_KEY", "STEPFUN_API_KEY"):
            os.environ.pop(k, None)
        try:
            rt = await assemble_plugin_runtime({})
            assert rt is not None
            await rt.close()
        finally:
            os.environ["GEMINI_API_KEY"] = "test-key"
            os.environ["ZHIPU_API_KEY"] = "test-key"
            os.environ["STEPFUN_API_KEY"] = "test-key"


class TestResolveDbPath:
    def test_returns_path_ending_in_pjsk_db(self) -> None:
        p = _resolve_db_path()
        assert p.name == "pjsk.db"
        assert "astrbot_plugin_pjsk" in str(p)

    def test_parent_directory_is_created(self, tmp_path: Path) -> None:
        """The resolved path's parent directory must exist after the call."""
        p = _resolve_db_path()
        assert p.parent.exists()
