"""Render difficulty ranking as a PNG image via the render service.

Transforms a DifficultyRanking into the JSON structure expected by
difficulty.js, prefetches jacket data URLs, and calls the Renderer port.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pjsk_core.domain.scores import ScoreStatus
from pjsk_core.ports.renderer import RenderPayload, Renderer

if TYPE_CHECKING:
    from adapters.rendering.jacket_cache import JacketCache
    from pjsk_core.domain.difficulty_ranking import (
        DifficultyRankEntry,
        DifficultyRanking,
    )

_logger = logging.getLogger(__name__)

_DIFF_ABBREV: dict[str, str] = {
    "master": "MA", "expert": "EX", "append": "APD",
    "hard": "HD", "normal": "NM", "easy": "EZ",
}


async def _prefetch_jackets(
    cache: JacketCache | None,
    song_ids: list[int],
) -> dict[int, str]:
    if cache is None:
        return {}
    try:
        return await cache.prefetch_jackets(song_ids)
    except Exception:
        _logger.warning("Jacket prefetch failed for difficulty ranking", exc_info=True)
        return {}


def _parse_constant(community_constant: str) -> float:
    """Parse community_constant string (e.g. '32.5+') to a float."""
    base = community_constant.rstrip("+-")
    tag = community_constant[len(base):] if len(base) < len(community_constant) else ""

    parts = base.split(".")
    integer = int(parts[0]) if parts[0] else 0
    decimal = parts[1] if len(parts) > 1 else "0"

    if decimal == "5+" or decimal.startswith("5") and tag == "+":
        frac = 0.55
    elif decimal.startswith("5"):
        frac = 0.5
    elif decimal.startswith("6"):
        frac = 0.6
    elif decimal.startswith("7"):
        frac = 0.7
    elif decimal.startswith("8"):
        frac = 0.8
    elif decimal.startswith("9"):
        frac = 0.9
    else:
        frac = float(f"0.{decimal}") if decimal else 0.0

    if tag == "+":
        frac += 0.05
    elif tag == "-":
        frac -= 0.05

    return float(integer) + frac


def _to_ranking_data(
    ranking: DifficultyRanking,
    jacket_map: dict[int, str],
) -> dict:
    """Transform DifficultyRanking into the JSON structure for difficulty.js."""
    # Group entries by community_constant, preserving sort order
    tiers: list[dict] = []
    current_constant: str | None = None
    current_songs: list[dict] = []

    for entry in ranking.entries:
        cc = entry.community_constant
        if cc != current_constant:
            if current_songs:
                tiers.append({
                    "constant": _parse_constant(current_constant or "0.0"),
                    "songs": current_songs,
                })
            current_constant = cc
            current_songs = []

        status: int = 0
        judges: dict | None = None
        acc: float = 0.0
        power: float = 0.0
        if entry.personal_best is not None:
            pb = entry.personal_best
            if pb.status == ScoreStatus.AP:
                status = 2
            elif pb.status == ScoreStatus.FC:
                status = 1
            judges = {
                "great": pb.judgements.great,
                "good": pb.judgements.good,
                "bad": pb.judgements.bad,
                "miss": pb.judgements.miss,
            }
            acc = pb.accuracy
            power = pb.rating

        current_songs.append({
            "jacket": jacket_map.get(entry.song_id),
            "status": status,
            "judges": judges,
            "accuracy": acc,
            "power": power,
        })

    if current_songs:
        tiers.append({
            "constant": _parse_constant(current_constant or "0.0"),
            "songs": current_songs,
        })

    abbrev = _DIFF_ABBREV.get(ranking.difficulty.value, ranking.difficulty.value.upper())

    return {
        "mode": ranking.mode,
        "title": f"{abbrev} {ranking.official_level}",
        "tiers": tiers,
    }


async def render_difficulty_ranking(
    ranking: DifficultyRanking,
    *,
    renderer: Renderer,
    jacket_cache: JacketCache | None = None,
) -> bytes | None:
    """Render a difficulty ranking image. Returns PNG bytes or None on failure."""
    song_ids = [e.song_id for e in ranking.entries]
    jacket_map = await _prefetch_jackets(jacket_cache, song_ids)

    data = _to_ranking_data(ranking, jacket_map)
    payload = RenderPayload(template_name="difficulty", data=data)

    try:
        png = await renderer.render(payload)
        if png is None:
            _logger.warning("Render service returned None for difficulty ranking")
        return png
    except Exception:
        _logger.warning("Difficulty ranking render failed", exc_info=True)
        return None
