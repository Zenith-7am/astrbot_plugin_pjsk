"""Entry-point smoke tests for benchmark_vision_engines.py.

Does NOT make real HTTP calls — only verifies import, --help, and registry.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


class TestBenchmarkImport:
    def test_module_imports_without_error(self) -> None:
        """benchmark_vision_engines must be importable without side-effects."""
        import tools.benchmark_vision_engines as bm
        assert hasattr(bm, "_ENGINE_BUILDERS")
        assert hasattr(bm, "main")

    def test_registry_contains_from_import(self) -> None:
        """Engine registry populated at import time via @_register decorators."""
        import tools.benchmark_vision_engines as bm
        assert "gemini" in bm._ENGINE_BUILDERS
        assert "zhipu" in bm._ENGINE_BUILDERS
        assert "stepfun" in bm._ENGINE_BUILDERS

    def test_help_returns_zero(self) -> None:
        """python tools/benchmark_vision_engines.py --help → exit 0."""
        result = subprocess.run(
            [sys.executable, "tools/benchmark_vision_engines.py", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, (
            f"--help failed with stderr:\n{result.stderr}"
        )
        assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower()


class TestTruthLoader:
    def test_rejects_non_object_top_level(self, tmp_path: Path) -> None:
        import json
        from tools.benchmark_vision_engines import _load_truth
        p = tmp_path / "truth.json"
        p.write_text(json.dumps(["not", "an", "object"]))
        import pytest
        with pytest.raises(ValueError, match="JSON object"):
            _load_truth(p)

    def test_rejects_missing_keys(self, tmp_path: Path) -> None:
        import json
        from tools.benchmark_vision_engines import _load_truth
        p = tmp_path / "truth.json"
        p.write_text(json.dumps({"img.png": {"song_title": "X"}}))
        import pytest
        with pytest.raises(ValueError, match="missing keys"):
            _load_truth(p)

    def test_loads_valid_truth(self, tmp_path: Path) -> None:
        import json
        from tools.benchmark_vision_engines import _load_truth
        p = tmp_path / "truth.json"
        entry = {
            "song_title": "Test", "difficulty": "MASTER", "level": 31,
            "perfect": 1, "great": 0, "good": 0, "bad": 0, "miss": 0,
        }
        p.write_text(json.dumps({"img.png": entry}))
        result = _load_truth(p)
        assert result["img.png"]["song_title"] == "Test"
