"""Renderer port — image rendering for query results."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RenderPayload:
    """Payload sent to the render service.

    template_name identifies which JS function to run (e.g. "b20", "difficulty").
    data is the pre-computed Python domain data serialized as JSON-compatible dict.
    """

    template_name: str
    data: dict[str, Any] = field(default_factory=dict)


class Renderer(Protocol):
    """Render domain data into a PNG image.

    Returns PNG bytes on success, or None on failure (render service
    unavailable or template error). Callers must degrade gracefully to
    text fallback when None is returned.
    """

    async def render(self, payload: RenderPayload) -> bytes | None: ...
