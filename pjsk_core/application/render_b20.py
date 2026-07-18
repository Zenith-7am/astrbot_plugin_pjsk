"""Render B20 ranking as a PNG image via the render service.

Transforms a B20Result into the JSON structure expected by b20.js,
prefetches jacket data URLs, and calls the Renderer port.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pjsk_core.domain.scores import ScoreStatus
from pjsk_core.ports.renderer import RenderPayload, Renderer

if TYPE_CHECKING:
    from adapters.rendering.jacket_cache import JacketCache
    from pjsk_core.domain.b20 import B20Result

_logger = logging.getLogger(__name__)


async def _prefetch_jackets(
    cache: JacketCache | None,
    song_ids: list[int],
) -> dict[int, str]:
    """Prefetch jacket data URLs for *song_ids*. Returns {song_id: data_url}."""
    if cache is None:
        return {}
    try:
        return await cache.prefetch_jackets(song_ids)
    except Exception:
        _logger.warning("Jacket prefetch failed for B20", exc_info=True)
        return {}


def _to_b20_data(result: B20Result, jacket_map: dict[int, str]) -> dict[str, object]:
    """Transform B20Result into the JSON structure expected by b20.js."""
    from pjsk_core.application.render_ocr_card import _get_acc_grade

    songs: list[dict[str, object]] = []
    for entry in result.entries:
        ap = entry.status == ScoreStatus.AP
        grade_label, grade_class = _get_acc_grade(entry.accuracy)
        songs.append({
            "jacket": jacket_map.get(entry.song_id),
            "achievementRate": None if ap else entry.accuracy,
            "status": 2 if ap else 1,  # 2=AP, 1=FC
            "difficulty": entry.difficulty.value,
            "displayLevel": entry.official_level,
            "level": entry.official_level,
            "title": entry.song_title,
            "power": entry.rating,
            "gradeLabel": grade_label,
            "gradeClass": grade_class,
            "judges": {
                "great": entry.judgements.great,
                "good": entry.judgements.good,
                "bad": entry.judgements.bad,
                "miss": entry.judgements.miss,
            },
        })
    return {
        "b20": songs,
        "isAppendExcluded": result.append_excluded,
        "currentPercentile": 0,
        "displayRank": "",
        "playerClass": {
            "name": result.player_class.name,
            "icon": result.player_class.icon,
            "stars": result.player_class.stars,
            "fallbackColor": result.player_class.fallback_color,
        },
        "sp": result.sp,
    }


async def render_b20(
    b20_result: B20Result,
    *,
    renderer: Renderer,
    jacket_cache: JacketCache | None = None,
) -> bytes | None:
    """Render a B20 ranking image. Returns PNG bytes or None on failure."""
    song_ids = [e.song_id for e in b20_result.entries]
    jacket_map = await _prefetch_jackets(jacket_cache, song_ids)
    _logger.info(
        "B20 jacket prefetch: requested=%d obtained=%d",
        len(song_ids), len(jacket_map),
    )

    data = _to_b20_data(b20_result, jacket_map)
    payload = RenderPayload(template_name="b20", data=data)

    try:
        png = await renderer.render(payload)
        if png is None:
            _logger.warning(
                "B20 render returned None: template=b20 entry_count=%d jacket_count=%d",
                len(b20_result.entries), len(jacket_map),
            )
        return png
    except Exception:
        _logger.warning("B20 render failed", exc_info=True)
        return None
