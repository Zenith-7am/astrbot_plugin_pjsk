"""Smoke tests for the Composition Root."""
import os
import tempfile
from pathlib import Path

import pytest
from plugin.bootstrap import assemble_plugin_runtime


@pytest.fixture(autouse=True)
def _vision_env() -> None:
    """Set dummy API keys so at least one vision engine is created.

    The engine constructors do NOT make network calls — they only store
    the arguments.  In CI, set these to any non-empty string.
    """
    os.environ.setdefault("GEMINI_API_KEY", "test-key")
    os.environ.setdefault("ZHIPU_API_KEY", "test-key")
    os.environ.setdefault("STEPFUN_API_KEY", "test-key")


@pytest.fixture
def temp_db() -> Path:
    return Path(tempfile.mktemp(suffix=".db"))


class TestBootstrap:
    async def test_assemble_returns_runtime(self, temp_db: Path) -> None:
        """Smoke test: assembly completes without error."""
        rt = await assemble_plugin_runtime(temp_db)
        assert rt is not None
        assert rt.user_repo is not None
        assert rt.recognize_score is not None
        assert rt.confirm_candidate is not None
        assert rt.candidate_store is not None
        assert rt.image_buffer is not None
        await rt.close()
