"""Renderer port — image generation for rankings and charts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RenderRequest:
    """Request to render a template with data."""

    template: str
    data: dict[str, object]
    width: int
    height: int


@dataclass(frozen=True)
class RenderResult:
    """Rendered image with version metadata for cache invalidation."""

    image_bytes: bytes
    renderer_version: str
    template_version: str


class Renderer(Protocol):
    """Rendering service adapter."""

    async def render(self, request: RenderRequest) -> RenderResult: ...
