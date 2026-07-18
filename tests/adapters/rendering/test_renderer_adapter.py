"""Tests for HttpRenderer adapter — HTTP → Renderer port."""

from unittest.mock import AsyncMock, patch

from pjsk_core.ports.renderer import RenderPayload, Renderer


class TestHttpRenderer:
    """Contract: HttpRenderer satisfies the Renderer Protocol."""

    async def test_conforms_to_renderer_protocol(self) -> None:
        """Structural conformance check."""
        from adapters.rendering.renderer_adapter import HttpRenderer

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")
        _: Renderer = renderer
        assert callable(renderer.render)

    async def test_successful_render_returns_bytes(self) -> None:
        """POST to render service → return PNG bytes."""
        from adapters.rendering.renderer_adapter import HttpRenderer

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.aread = AsyncMock(return_value=b"png-data")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = RenderPayload(template_name="b20", data={"sp": 12345})
            result = await renderer.render(payload)

        assert result == b"png-data"

    async def test_non_200_returns_none(self) -> None:
        """HTTP 500 from render service → return None."""
        from adapters.rendering.renderer_adapter import HttpRenderer

        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = RenderPayload(template_name="b20", data={})
            result = await renderer.render(payload)

        assert result is None

    async def test_connection_error_returns_none(self) -> None:
        """Connection refused → return None gracefully."""
        from adapters.rendering.renderer_adapter import HttpRenderer

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=OSError("connection refused"))

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = RenderPayload(template_name="b20", data={})
            result = await renderer.render(payload)

        assert result is None

    async def test_timeout_returns_none(self) -> None:
        """Request timeout → return None gracefully."""
        from adapters.rendering.renderer_adapter import HttpRenderer
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000", timeout=5.0)

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = RenderPayload(template_name="b20", data={})
            result = await renderer.render(payload)

        assert result is None

    async def test_custom_base_url(self) -> None:
        """POST URL is built correctly from base_url."""
        from adapters.rendering.renderer_adapter import HttpRenderer

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.read = AsyncMock(return_value=b"png")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        renderer = HttpRenderer(base_url="http://custom:4000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = RenderPayload(template_name="difficulty", data={"mode": "global"})
            await renderer.render(payload)

        # Verify the correct URL was POSTed
        call_args = mock_client.post.call_args
        assert call_args is not None
        url = call_args[0][0]
        assert url == "http://custom:4000/render/difficulty"

    async def test_json_serialization(self) -> None:
        """RenderPayload.data is JSON-serialized in request body."""
        from adapters.rendering.renderer_adapter import HttpRenderer

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.read = AsyncMock(return_value=b"png")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = RenderPayload(
                template_name="b20",
                data={"sp": 34567.89, "entries": [{"title": "幾望の月"}]},
            )
            await renderer.render(payload)

        # Verify JSON content was sent
        call_args = mock_client.post.call_args
        assert call_args is not None
        # httpx.AsyncClient.post(json=...) sends JSON body
        assert call_args[1].get("json") == payload.data



class TestDiagnosticLogging:
    """Verify diagnostic logs are emitted without changing return values."""

    async def test_success_logs_request_and_response(self) -> None:
        from unittest.mock import AsyncMock, patch
        from adapters.rendering.renderer_adapter import HttpRenderer
        from pjsk_core.ports.renderer import RenderPayload

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.aread = AsyncMock(return_value=b"png-data")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("adapters.rendering.renderer_adapter.logger.info") as mock_info:
                payload = RenderPayload(template_name="b20", data={"sp": 12345})
                result = await renderer.render(payload)

        assert result == b"png-data"  # return value unchanged
        # First call: request, second call: response
        assert mock_info.call_count == 2
        req_call = mock_info.call_args_list[0]
        assert req_call[0][0] == "Render request: template=%s host=%s path=%s"
        assert req_call[0][1] == "b20"
        assert req_call[0][2] == "127.0.0.1"
        assert "/render/b20" in req_call[0][3]
        resp_call = mock_info.call_args_list[1]
        assert resp_call[0][0] == "Render response: template=%s status=%d content_type=%s bytes=%d"
        assert resp_call[0][1] == "b20"
        assert resp_call[0][2] == 200
        assert resp_call[0][3] == "image/png"
        assert resp_call[0][4] == 8

    async def test_non_200_logs_warning(self) -> None:
        from unittest.mock import AsyncMock, patch
        from adapters.rendering.renderer_adapter import HttpRenderer
        from pjsk_core.ports.renderer import RenderPayload

        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_response.content = b"error"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        renderer = HttpRenderer(base_url="http://128.0.0.1:4000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("adapters.rendering.renderer_adapter.logger.warning") as mock_warn:
                payload = RenderPayload(template_name="ocr", data={})
                result = await renderer.render(payload)

        assert result is None  # return value unchanged
        assert mock_warn.call_count == 1
        call = mock_warn.call_args_list[0]
        assert call[0][0] == "Render response: template=%s status=%d content_type=%s bytes=%d"
        assert call[0][1] == "ocr"
        assert call[0][2] == 503
        assert call[0][3] == "text/plain"
        assert call[0][4] == 5

    async def test_timeout_logs_template_and_timeout(self) -> None:
        from unittest.mock import AsyncMock, patch
        from adapters.rendering.renderer_adapter import HttpRenderer
        from pjsk_core.ports.renderer import RenderPayload
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000", timeout=7.0)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("adapters.rendering.renderer_adapter.logger.warning") as mock_warn:
                payload = RenderPayload(template_name="b20", data={})
                result = await renderer.render(payload)

        assert result is None  # return value unchanged
        assert mock_warn.call_count == 1
        call = mock_warn.call_args_list[0]
        assert call[0][0] == "Render timeout: template=%s timeout=%s"
        assert call[0][1] == "b20"
        assert call[0][2] == 7.0

    async def test_connection_error_logs_type_and_message(self) -> None:
        from unittest.mock import AsyncMock, patch
        from adapters.rendering.renderer_adapter import HttpRenderer
        from pjsk_core.ports.renderer import RenderPayload

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=OSError("connection refused"))

        renderer = HttpRenderer(base_url="http://127.0.0.1:3000")

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("adapters.rendering.renderer_adapter.logger.warning") as mock_warn:
                payload = RenderPayload(template_name="difficulty", data={})
                result = await renderer.render(payload)

        assert result is None  # return value unchanged
        assert mock_warn.call_count == 1
        call = mock_warn.call_args_list[0]
        assert call[0][0] == "Render failed: template=%s error_type=%s message=%s"
        assert call[0][1] == "difficulty"
        assert call[0][2] == "OSError"
        assert call[0][3] == "connection refused"
        # exc_info should be True
        assert call[1].get("exc_info") is True
