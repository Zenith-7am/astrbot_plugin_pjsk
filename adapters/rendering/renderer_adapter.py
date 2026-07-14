"""HTTP adapter implementing the Renderer port.

POSTs to a render service (e.g. ``http://127.0.0.1:3000``) and returns
the resulting PNG bytes. Returns ``None`` on any failure — callers must
degrade gracefully to text fallback.

Accepts an optional shared ``httpx.AsyncClient`` for connection reuse.
When omitted, a new client is created per render call.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from pjsk_core.ports.renderer import RenderPayload

logger = logging.getLogger("pjsk.renderer_adapter")


class HttpRenderer:
    """Render service HTTP client.

    POSTs ``/render/{payload.template_name}`` with JSON body
    ``payload.data``. Timeouts and connection errors are caught;
    ``render()`` never raises.

    Pass *client* to reuse a shared ``httpx.AsyncClient`` (managed
    externally — the renderer never closes it).
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000",
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def render(self, payload: RenderPayload) -> bytes | None:
        """POST *payload* to the render service, return PNG bytes or None."""
        url = f"{self._base_url}/render/{payload.template_name}"
        try:
            if self._client is not None:
                resp = await self._client.post(
                    url, json=payload.data, timeout=self._timeout,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Render service returned %d for %s",
                        resp.status_code,
                        payload.template_name,
                    )
                    return None
                return await resp.aread()
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload.data)
                    if resp.status_code != 200:
                        logger.warning(
                            "Render service returned %d for %s",
                            resp.status_code,
                            payload.template_name,
                        )
                        return None
                    return await resp.aread()
        except httpx.TimeoutException:
            logger.warning("Render service timeout for %s", payload.template_name)
            return None
        except Exception:
            logger.warning(
                "Render service unreachable for %s",
                payload.template_name,
                exc_info=True,
            )
            return None
