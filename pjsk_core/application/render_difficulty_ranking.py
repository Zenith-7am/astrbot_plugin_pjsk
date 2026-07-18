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
    from pjsk_core.domain.difficulty_ranking import DifficultyRanking

_logger = logging.getLogger(__name__)

_DIFF_ABBREV: dict[str, str] = {
    "master": "MA", "expert": "EX", "append": "APD",
    "hard": "HD", "normal": "NM", "easy": "EZ",
}


def _resolve_jacket_urls(
    cache: JacketCache | None,
    song_ids: list[int],
) -> dict[int, str]:
    """Resolve jacket ``file://`` URLs for *song_ids* (no base64 in payload)."""
    if cache is None:
        return {}
    result: dict[int, str] = {}
    for sid in song_ids:
        url = cache.get_jacket_file_url(sid)
        if url is not None:
            result[sid] = url
    return result


def _to_ranking_data(
    ranking: DifficultyRanking,
    jacket_map: dict[int, str],
) -> dict[str, object]:
    """Transform DifficultyRanking into the JSON structure for difficulty.js."""
    # Group entries by community_constant, preserving sort order
    tiers: list[dict[str, object]] = []
    current_constant: str | None = None
    current_songs: list[dict[str, object]] = []

    for entry in ranking.entries:
        cc = entry.community_constant
        if cc != current_constant:
            if current_songs:
                tiers.append({
                    "constant_label": current_constant or "0.0",
                    "songs": current_songs,
                })
            current_constant = cc
            current_songs = []

        status: int = 0
        judges: dict[str, int] | None = None
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
            "constant_label": current_constant or "0.0",
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
    jacket_map = _resolve_jacket_urls(jacket_cache, song_ids)

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
