"""Shared utilities for vision engine adapters.

All adapters import from here instead of duplicating:
- ``_DIFF_MAP`` — difficulty string → Difficulty enum
- ``_encode_base64`` — bytes → Base64-encoded ASCII string
- ``_extract_json`` — extract JSON from model responses (bare or fenced)
- ``_parse_ocr_json`` — parse extracted JSON string → OcrObservation
- ``_FENCED_JSON_RE`` — compiled regex used by ``_extract_json``
"""
from __future__ import annotations

import base64 as _base64
import json
import re

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import (
    OcrObservation,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements

_DIFF_MAP: dict[str, Difficulty] = {
    "EASY": Difficulty.EASY,
    "NORMAL": Difficulty.NORMAL,
    "HARD": Difficulty.HARD,
    "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER,
    "APPEND": Difficulty.APPEND,
}

_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

_REJECTED_SONG_TITLES: frozenset[str] = frozenset({
    # UI labels that models sometimes misread as the song title.
    # These are NEVER valid song names — reject them immediately.
    "スコア",    # "Score" — result screen header
    "リザルト",   # "Result" — result screen tab
    "楽曲",      # "Song" — UI section label
    "クリア",    # "Clear" — clear status label
    "クリア済み", # "Cleared"
    "FULL COMBO",
    "ALL PERFECT",
    "PERFECT",
    "GREAT",
    "GOOD",
    "BAD",
    "MISS",
    "COMBO",
    "判定",      # "Judgement" — judgement section header
    "達成率",    # "Accuracy rate"
    "順位",      # "Rank"
    "難易度",    # "Difficulty" — difficulty label
})


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


def _parse_ocr_json(json_text: str, engine_id: str) -> OcrObservation:
    """Parse a JSON string from a vision model response into an OcrObservation.

    All four adapters share this function.  Each adapter is responsible for
    extracting the JSON string from its vendor-specific response envelope;
    this function handles the common parsing, field validation, and domain
    object construction.

    Args:
        json_text: The extracted JSON string (after fence stripping if needed).
        engine_id: The engine identity string (e.g. ``"gemini-gemini-2.5-flash"``).

    Returns:
        A fully validated :class:`OcrObservation`.

    Raises:
        VisionResponseError: If any required field is missing, invalid, or
            the JSON cannot be parsed.
    """
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise VisionResponseError(f"Invalid JSON response: {e}") from e

    # song_title — required, non-empty after strip
    song_title = str(parsed.get("song_title", "")).strip()
    if not song_title:
        raise VisionResponseError("song_title is missing or empty")
    if song_title in _REJECTED_SONG_TITLES:
        raise VisionResponseError(
            f"song_title is a UI label, not a song name: {song_title!r}"
        )

    # difficulty — required, must be a known enum value
    difficulty_str = str(parsed.get("difficulty", "")).upper()
    difficulty = _DIFF_MAP.get(difficulty_str)
    if difficulty is None:
        raise VisionResponseError(
            f"Unknown difficulty: {parsed.get('difficulty')!r}"
        )

    # level — required, positive integer
    try:
        level = int(parsed["level"])
    except (KeyError, ValueError, TypeError) as e:
        raise VisionResponseError(
            f"Invalid or missing level: {e}"
        ) from e
    if level <= 0:
        raise VisionResponseError(
            f"level must be positive, got: {level}"
        )

    # judgements — all 5 required, non-negative integers
    try:
        perfect = int(parsed["perfect"])
        great = int(parsed["great"])
        good = int(parsed["good"])
        bad = int(parsed["bad"])
        miss = int(parsed["miss"])
    except (KeyError, ValueError, TypeError) as e:
        raise VisionResponseError(
            f"Missing or invalid judgement field: {e}"
        ) from e

    for name, val in [
        ("perfect", perfect), ("great", great),
        ("good", good), ("bad", bad), ("miss", miss),
    ]:
        if val < 0:
            raise VisionResponseError(
                f"Negative judgement count: {name}={val}"
            )

    return OcrObservation(
        song_title=song_title,
        difficulty=difficulty,
        displayed_level=level,
        judgements=Judgements(
            perfect=perfect, great=great, good=good, bad=bad, miss=miss,
        ),
        engine=engine_id,
        elapsed_ms=0,
    )
