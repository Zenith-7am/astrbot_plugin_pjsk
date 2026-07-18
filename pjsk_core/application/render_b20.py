"""Render B20 ranking as a PNG image via the render service.

POSTs a pre-assembled JSON payload to ``POST /render/b20`` and returns
PNG bytes.  The caller (handler) is responsible for building the complete
payload — this function does no data translation.
"""
from __future__ import annotations

import logging

from pjsk_core.ports.renderer import RenderPayload, Renderer

_logger = logging.getLogger(__name__)


async def render_b20(
    data: dict[str, object],
    *,
    renderer: Renderer,
) -> bytes | None:
    """Render B20 from a complete JS payload. Returns PNG bytes or None."""
    payload = RenderPayload(template_name="b20", data=data)
    try:
        png = await renderer.render(payload)
        if png is None:
            _logger.warning("B20 render returned None")
        return png
    except Exception:
        _logger.warning("B20 render failed", exc_info=True)
        return None
