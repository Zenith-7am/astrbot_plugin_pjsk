"""Shared utilities for vision engine adapters.

All adapters import from here instead of duplicating:
- ``_DIFF_MAP`` — difficulty string → Difficulty enum
- ``_encode_base64`` — bytes → Base64-encoded ASCII string
- ``_extract_json`` — extract JSON from model responses (bare or fenced)
- ``_FENCED_JSON_RE`` — compiled regex used by ``_extract_json``
"""
from __future__ import annotations

import base64 as _base64
import re

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import VisionResponseError

_DIFF_MAP: dict[str, Difficulty] = {
    "EASY": Difficulty.EASY,
    "NORMAL": Difficulty.NORMAL,
    "HARD": Difficulty.HARD,
    "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER,
    "APPEND": Difficulty.APPEND,
}

_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Return the JSON substring from *text*.

    Handles three forms:
    1. Bare JSON: ``text`` starts with ``{`` after optional whitespace.
    2. Fenced JSON: `` ```json {...} ``` `` block.
    3. Whitespace-only padding is ignored.

    Raises :exc:`VisionResponseError` when no JSON-like content is found.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    m = _FENCED_JSON_RE.search(stripped)
    if m is not None:
        return m.group(1)
    raise VisionResponseError(
        f"Response is not bare JSON or fenced JSON. "
        f"First 200 chars: {stripped[:200]!r}"
    )


def _encode_base64(data: bytes) -> str:
    """Encode *data* as a Base64 ASCII string (no line breaks)."""
    return _base64.b64encode(data).decode("ascii")
