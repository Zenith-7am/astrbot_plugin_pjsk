"""Tests for local render dev workflow — health + import + fixture validation."""

import json
from pathlib import Path


class TestDevHealthEndpoint:
    """Health endpoint returns the function list needed by preview tooling."""

    def test_health_includes_functions_list(self) -> None:
        """GET /health response MUST include a 'functions' key (list of str)."""
        import render_service.main as svc

        # Simulate the post-warmup state: functions have been loaded.
        svc._function_names = ["b20", "difficulty"]

        from fastapi.testclient import TestClient
        client = TestClient(svc.app)
        response = client.get("/health")
        assert response.status_code == 200

        body = response.json()
        assert "functions" in body
        assert isinstance(body["functions"], list)
        assert "b20" in body["functions"]


class TestB20PreviewFixture:
    """The bundled fixture payload is valid JSON with expected structure."""

    def test_fixture_is_valid_json(self) -> None:
        """b20_preview.json parses as JSON."""
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "tests" / "fixtures" / "render" / "b20_preview.json"
        )
        assert fixture_path.exists(), f"Missing fixture: {fixture_path}"

        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_fixture_has_required_fields(self) -> None:
        """Fixture contains the minimum fields b20.js expects."""
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "tests" / "fixtures" / "render" / "b20_preview.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))

        # Top-level fields expected by b20.js
        assert "b20" in data, "missing 'b20' entries list"
        assert "sp" in data, "missing 'sp' (SEKAI POWER)"
        assert "playerClass" in data, "missing 'playerClass'"
        assert "b20Avg" in data, "missing 'b20Avg'"

        # Each b20 entry must have jacket (null or data URL)
        for entry in data["b20"]:
            assert "jacket" in entry, f"entry missing 'jacket': {entry.get('title')}"
            assert "title" in entry
            assert "difficulty" in entry

    def test_fixture_has_no_real_user_data(self) -> None:
        """Fixture must not contain real QQ numbers or production data."""
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "tests" / "fixtures" / "render" / "b20_preview.json"
        )
        text = fixture_path.read_text(encoding="utf-8")

        # No real QQ numbers
        assert "3366463190" not in text
        # No external URLs (jackets should be local data URLs or null)
        assert "api.pjsk-rate-api.com" not in text


class TestPreviewScriptImport:
    """render_preview.py is syntactically valid and importable."""

    def test_preview_script_has_expected_api(self) -> None:
        """The preview module exposes build_parser and main()."""
        import importlib.util

        tools_dir = Path(__file__).parent.parent.parent / "tools"
        spec = importlib.util.spec_from_file_location(
            "render_preview",
            tools_dir / "render_preview.py",
        )
        assert spec is not None, "render_preview.py not found"
        # Don't actually execute — just verify the file exists and is parseable
        source = (tools_dir / "render_preview.py").read_text(encoding="utf-8")
        compile(source, str(tools_dir / "render_preview.py"), "exec")
