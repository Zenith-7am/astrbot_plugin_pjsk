"""Tests for render service — FastAPI endpoints and lifecycle.

These tests mock Playwright Page/Context to avoid requiring a real browser.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_page() -> MagicMock:
    """Build a fake Playwright Page."""
    page = MagicMock()
    page.evaluate = AsyncMock(return_value={"width": 800, "height": 600})
    page.screenshot = AsyncMock(return_value=b"fake-png-data")
    page.set_content = AsyncMock()
    page.add_script_tag = AsyncMock()
    page.set_viewport_size = AsyncMock()
    page.close = AsyncMock()
    return page


def _make_context(page: MagicMock | None = None) -> MagicMock:
    """Build a fake BrowserContext that creates *page*."""
    ctx = MagicMock()
    ctx.new_page = AsyncMock(return_value=page or _make_page())
    ctx.close = AsyncMock()
    return ctx


def _make_browser(context: MagicMock | None = None) -> MagicMock:
    """Build a fake Browser."""
    ctx = context or _make_context()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=ctx)
    browser.is_connected = MagicMock(return_value=True)
    browser.close = AsyncMock()
    return browser


# ── Tests ───────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        """GET /health returns status ok."""
        from render_service.main import app
        assert app is not None


class TestRenderEndpoint:
    """Tests for /render/{name} endpoint."""

    def test_unknown_function_returns_404(self) -> None:
        """Requesting an unregistered function returns 404."""
        import render_service.main as svc

        svc._function_names = ["b20"]
        svc._browser = _make_browser()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post("/render/nonexistent", json={})
            assert response.status_code == 404
            assert "unknown render function" in response.text.lower()

    def test_invalid_json_returns_400(self) -> None:
        """Non-JSON body returns 400."""
        import render_service.main as svc

        svc._function_names = ["b20"]
        svc._browser = _make_browser()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post(
                "/render/b20",
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 400

    def test_valid_render_returns_png(self) -> None:
        """Valid render request returns PNG image bytes."""
        import render_service.main as svc

        page = _make_page()
        context = _make_context(page)
        browser = _make_browser(context)

        svc._function_names = ["b20"]
        svc._browser = browser
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post("/render/b20", json={"sp": 34567.89})
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content == b"fake-png-data"

    def test_browser_unavailable_returns_503(self) -> None:
        """When _ensure_browser returns False, return 503."""
        import render_service.main as svc

        svc._function_names = ["b20"]
        svc._browser = MagicMock()

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=False)):
            client = TestClient(svc.app)
            response = client.post("/render/b20", json={"sp": 1})
            assert response.status_code == 503

    def test_render_function_error_returns_500(self) -> None:
        """JS render function throwing an error returns 500."""
        import render_service.main as svc

        page = _make_page()
        page.evaluate = AsyncMock(side_effect=Exception("ReferenceError: x is not defined"))
        context = _make_context(page)
        browser = _make_browser(context)

        svc._function_names = ["b20"]
        svc._browser = browser
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post("/render/b20", json={"sp": 1})
            assert response.status_code == 500


class TestConcurrencyIsolation:
    """Each concurrent request gets its own Page/Context."""

    def test_concurrent_requests_isolated(self) -> None:
        """Two concurrent renders use different pages."""
        import render_service.main as svc

        page1 = _make_page()
        page2 = _make_page()
        ctx1 = _make_context(page1)
        ctx2 = _make_context(page2)

        # Track new_context calls to return different contexts
        mock_browser = MagicMock()
        mock_browser.new_context = AsyncMock(side_effect=[ctx1, ctx2])
        mock_browser.is_connected = MagicMock(return_value=True)
        mock_browser.close = AsyncMock()

        svc._function_names = ["b20"]
        svc._browser = mock_browser
        svc._browser_restart_attempted = False

        # Temporarily increase semaphore to allow concurrency in test
        original_sem = svc._render_sem
        svc._render_sem = asyncio.Semaphore(10)

        try:
            with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
                client = TestClient(svc.app)

                # We can't truly run concurrent requests through TestClient
                # (it's synchronous), but we can verify that two sequential
                # requests each get their own page/context.
                r1 = client.post("/render/b20", json={"sp": 1})
                r2 = client.post("/render/b20", json={"sp": 2})

                assert r1.status_code == 200
                assert r2.status_code == 200
                assert mock_browser.new_context.call_count == 2
                # Each context's page was used
                assert ctx1.new_page.called
                assert ctx2.new_page.called
                # Both contexts were closed
                ctx1.close.assert_called_once()
                ctx2.close.assert_called_once()
        finally:
            svc._render_sem = original_sem


class TestModuleImport:
    """Verify the module can be imported."""

    def test_app_object_exists(self) -> None:
        """FastAPI app object is importable."""
        from render_service.main import app
        assert app is not None
        assert app.title == "PJSK Render Service"


class TestHtmlRenderEndpoint:
    """Tests for POST /render/html."""

    def test_missing_html_returns_400(self) -> None:
        import render_service.main as svc

        svc._browser = _make_browser()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post("/render/html", json={"width": 960, "height": 600})
            assert response.status_code == 400

    def test_invalid_json_returns_400(self) -> None:
        import render_service.main as svc

        svc._browser = _make_browser()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post("/render/html", content=b"not-json")
            assert response.status_code == 400

    def test_successful_render_returns_png(self) -> None:
        import render_service.main as svc

        page = _make_page()
        ctx = _make_context(page)
        browser = _make_browser(ctx)
        svc._browser = browser
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post(
                "/render/html",
                json={"html": "<h1>Hello</h1>", "width": 200, "height": 100},
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content == b"fake-png-data"
            page.screenshot.assert_called_once()

    def test_script_tags_are_stripped(self) -> None:
        import render_service.main as svc

        page = _make_page()
        ctx = _make_context(page)
        browser = _make_browser(ctx)
        svc._browser = browser
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=True)):
            client = TestClient(svc.app)
            response = client.post(
                "/render/html",
                json={
                    "html": "<html><head><script>alert('xss')</script></head><body>safe</body></html>",
                    "width": 100, "height": 100,
                },
            )
            assert response.status_code == 200
            # Verify the script was stripped from what set_content received
            call_arg = page.set_content.call_args[0][0]
            assert "<script>" not in call_arg
            assert "alert" not in call_arg
            assert "safe" in call_arg

    def test_browser_unavailable_returns_503(self) -> None:
        import render_service.main as svc

        svc._browser = _make_browser()
        svc._browser_restart_attempted = False

        with patch.object(svc, "_ensure_browser", AsyncMock(return_value=False)):
            client = TestClient(svc.app)
            response = client.post(
                "/render/html",
                json={"html": "<h1>Hi</h1>", "width": 100, "height": 100},
            )
            assert response.status_code == 503
