"""Jacket image cache — local disk → CDN fallback → data URL.

CDN base URL: https://api.pjsk-rate-api.com/music/jacket/
Max 5 concurrent CDN fetches. Cache files named ``{song_id}.webp``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile

import httpx

logger = logging.getLogger("pjsk.jacket_cache")

CDN_URL = (
    "https://api.pjsk-rate-api.com/music/jacket/"
    "thumbnail_{song_id}/thumbnail_{song_id}.webp?v=2"
)
_FETCH_SEM = asyncio.Semaphore(5)

# Minimum file size for a valid jacket image (avoids treating
# truncated / zero-byte files as cached). A real WebP is ≥100 bytes.
_MIN_FILE_SIZE = 100


def _build_cdn_url(song_id: int) -> str:
    """Build the CDN jacket URL for a given song id."""
    return CDN_URL.format(song_id=song_id)


class JacketCache:
    """Local disk cache for PJSK song jacket images.

    Cache misses are fetched from the CDN (up to 5 concurrent) and
    written to disk. All public methods return ``data:image/webp;base64,…``
    data URLs or ``None`` when the image is unavailable.
    """

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "pjsk_jackets")
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- public API ----------------------------------------------------------

    async def get_jacket(self, song_id: int) -> str | None:
        """Return the jacket data URL for *song_id*, or ``None``."""
        data_url = await self._load_from_cache(song_id)
        if data_url is not None:
            return data_url

        async with _FETCH_SEM:
            return await self._fetch_from_cdn(song_id)

    async def prefetch_jackets(self, song_ids: list[int]) -> dict[int, str]:
        """Download multiple jackets concurrently.

        Returns a dict mapping each *song_id* to its data URL (or
        ``None`` for songs whose jacket could not be fetched).
        """

        async def _resolve(sid: int) -> tuple[int, str | None]:
            return sid, await self.get_jacket(sid)

        results = await asyncio.gather(*(_resolve(sid) for sid in song_ids))
        return {sid: data_url for sid, data_url in results if data_url is not None}

    # -- internal ------------------------------------------------------------

    def _cache_path(self, song_id: int) -> str:
        return os.path.join(self.cache_dir, f"{song_id}.webp")

    async def _load_from_cache(self, song_id: int) -> str | None:
        path = self._cache_path(song_id)
        if not os.path.exists(path):
            return None
        try:
            size = os.path.getsize(path)
        except OSError:
            return None
        if size < _MIN_FILE_SIZE:
            return None
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        return f"data:image/webp;base64,{base64.b64encode(data).decode()}"

    async def _fetch_from_cdn(self, song_id: int) -> str | None:
        url = _build_cdn_url(song_id)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                content = resp.content
        except Exception:
            logger.debug("Jacket CDN fetch failed: %d", song_id, exc_info=True)
            return None

        data_url = f"data:image/webp;base64,{base64.b64encode(content).decode()}"

        # Write-through cache
        path = self._cache_path(song_id)
        try:
            with open(path, "wb") as f:
                f.write(content)
            logger.debug("Jacket cached: %d (%d bytes)", song_id, len(content))
        except OSError:
            logger.debug("Jacket cache write failed: %d", song_id)

        return data_url
