"""Image format utilities — PNG→JPEG conversion for QQ message size reduction.

PNG renders from the render service are typically 200-500 KB. JPEG at
quality 85 is 3-5× smaller with minimal visual difference on mobile.
"""
from __future__ import annotations

import logging
from io import BytesIO

from PIL import Image

_logger = logging.getLogger(__name__)


def png_to_jpeg(png: bytes, quality: int = 85) -> bytes | None:
    """Convert PNG bytes to JPEG bytes. Returns None on invalid input."""
    try:
        img = Image.open(BytesIO(png))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        _logger.warning("PNG→JPEG conversion failed", exc_info=True)
        return None
