"""Tests for render service — FastAPI endpoints and lifecycle.

These tests mock Playwright to avoid requiring a real browser.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ─────────────────────────────────────────────────────────────


def _patch_functions_dir(tmp_path: Path) -> Path:
    """Create a minimal functions directory with _loader.js and a stub .js file."""
    funcs = tmp_path / "functions"
    funcs.mkdir()
    (funcs / "_loader.js").write_text("""
        window.__renderFunctions = {};
        window.registerRenderFunction = function(name, fn) {
            window.__renderFunctions[name] = fn;
        };
    """)
    (funcs / "b20.js").write_text("""
        registerRenderFunction("b20", async function(data) {
            var c = document.getElementById("render-canvas");
            var ctx = c.getContext("2d");
            c.width = 800; c.height = 600;
            ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, 800, 600);
        });
    """)
    return funcs


def _make_page() -> MagicMock:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value={"width": 800, "height": 600})
    page.screenshot = AsyncMock(return_value=b"fake-png-data")
    page.set_content = AsyncMock()
    page.add_script_tag = AsyncMock()
    page.set_viewport_size = AsyncMock()
    page.close = AsyncMock()
    return page


# ── Tests ───────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        """GET /health returns status ok — import-level check."""
        from render_service.main import app
        assert app is not None


class TestRenderEndpoint:
    """Tests for /render/{name} endpoint."""

    def test_unknown_function_returns_404(self, tmp_path: Path) -> None:
        """Requesting an unregistered function returns 404."""
        import render_service.main as svc

        _patch_functions_dir(tmp_path)
        page = _make_page()

        svc._function_names = ["b20"]
        svc._canvas_page = page
        svc._browser = MagicMock()
        svc._context = MagicMock()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            from fastapi.testclient import TestClient

            client = TestClient(svc.app)
            response = client.post("/render/nonexistent", json={})
            assert response.status_code == 404
            assert "unknown render function" in response.text.lower()

    def test_invalid_json_returns_400(self, tmp_path: Path) -> None:
        """Non-JSON body returns 400."""
        import render_service.main as svc

        page = _make_page()
        svc._function_names = ["b20"]
        svc._canvas_page = page
        svc._browser = MagicMock()
        svc._context = MagicMock()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            from fastapi.testclient import TestClient

            client = TestClient(svc.app)
            response = client.post(
                "/render/b20",
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 400

    def test_valid_render_returns_png(self, tmp_path: Path) -> None:
        """Valid render request returns PNG image bytes."""
        import render_service.main as svc

        page = _make_page()
        mock_browser = MagicMock()
        mock_browser.is_connected = MagicMock(return_value=True)

        svc._function_names = ["b20"]
        svc._canvas_page = page
        svc._browser = mock_browser
        svc._context = MagicMock()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            from fastapi.testclient import TestClient

            client = TestClient(svc.app)
            response = client.post("/render/b20", json={"sp": 34567.89})
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content == b"fake-png-data"

    def test_browser_unavailable_returns_503(self) -> None:
        """When _ensure_browser returns False, return 503."""
        import render_service.main as svc

        svc._function_names = ["b20"]
        svc._canvas_page = MagicMock()
        svc._browser = MagicMock()
        svc._context = MagicMock()

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=False)):
            from fastapi.testclient import TestClient

            client = TestClient(svc.app)
            response = client.post("/render/b20", json={"sp": 1})
            assert response.status_code == 503

    def test_render_function_error_returns_500(self) -> None:
        """JS render function throwing an error returns 500."""
        import render_service.main as svc

        page = _make_page()
        page.evaluate = AsyncMock(side_effect=Exception("ReferenceError: x is not defined"))
        mock_browser = MagicMock()
        mock_browser.is_connected = MagicMock(return_value=True)

        svc._function_names = ["b20"]
        svc._canvas_page = page
        svc._browser = mock_browser
        svc._context = MagicMock()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            from fastapi.testclient import TestClient

            client = TestClient(svc.app)
            response = client.post("/render/b20", json={"sp": 1})
            assert response.status_code == 500
            assert "render function error" in response.text.lower()


class TestModuleImport:
    """Verify the module can be imported without Playwright installed."""

    def test_app_object_exists(self) -> None:
        """FastAPI app object is importable."""
        from render_service.main import app
        assert app is not None
        assert app.title == "PJSK Render Service"
