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
