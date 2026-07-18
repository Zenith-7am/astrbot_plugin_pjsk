"""Jacket image cache — local disk → CDN fallback → data URL.

Reads legacy PNG/JPEG and new WebP files from a shared persistent
directory. On cache miss, an **opt-in** CDN fallback downloads and
caches as ``{song_id}.webp``. All public methods return
``data:<mime>;base64,…`` data URLs or ``None``.

CDN base URL: https://api.pjsk-rate-api.com/music/jacket/
Max 5 concurrent CDN fetches. Cache writes are atomic (temp file +
atomic replace).

When the cache directory is unset, unwritable, or fails the write
probe, the instance sets ``cache_disabled = True`` and operates in
read-only / no-op mode — no crash, no effect on OCR/B20/text fallback.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from typing import Optional

import httpx

logger = logging.getLogger("pjsk.jacket_cache")

CDN_URL = (
    "https://api.pjsk-rate-api.com/music/jacket/"
    "thumbnail_{song_id}/thumbnail_{song_id}.webp?v=2"
)
_FETCH_SEM = asyncio.Semaphore(5)

# Minimum file size for a valid jacket image (avoids treating
# truncated / zero-byte files as cached).
_MIN_FILE_SIZE = 100

# ── Image format detection ───────────────────────────────────────────────

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SIG = b"\xff\xd8\xff"
_WEBP_RIFF = b"RIFF"
_WEBP_FOURCC = b"WEBP"

_MIME_MAP: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def _detect_format(data: bytes) -> str | None:
    """Return 'png', 'jpeg', or 'webp' if *data* has a valid image header.

    Returns None for unrecognised or corrupt data.
    """
    if len(data) < _MIN_FILE_SIZE:
        return None
    if data[:len(_PNG_SIG)] == _PNG_SIG:
        return "png"
    if data[:len(_JPEG_SIG)] == _JPEG_SIG:
        return "jpeg"
    if data[:4] == _WEBP_RIFF and len(data) >= 12 and data[8:12] == _WEBP_FOURCC:
        return "webp"
    return None


def _build_cdn_url(song_id: int) -> str:
    return CDN_URL.format(song_id=song_id)


# ── Candidate cache paths (lookup order = priority) ─────────────────────


def _candidate_paths(cache_dir: str, song_id: int) -> list[str]:
    """Return candidate file paths for *song_id* in priority order.

    #1 is the canonical new format (``{id}.webp``); later entries are
    legacy naming conventions from the old emu-bot era.
    """
    padded = f"{song_id:03d}"
    return [
        os.path.join(cache_dir, f"{song_id}.webp"),
        os.path.join(cache_dir, f"{song_id}.png"),
        os.path.join(cache_dir, f"{song_id}.jpg"),
        os.path.join(cache_dir, f"{padded}.png"),
        os.path.join(cache_dir, f"jacket_s_{padded}.png"),
        os.path.join(cache_dir, f"{padded}.jpg"),
    ]


# ── JacketCache ──────────────────────────────────────────────────────────


class JacketCache:
    """Local disk cache for PJSK song jacket images.

    Reads legacy PNG/JPEG and new WebP files. On cache miss, an opt-in
    CDN fallback downloads and caches as ``{song_id}.webp``.

    Pass *client* to reuse a shared ``httpx.AsyncClient`` (managed
    externally — JacketCache never closes it).

    *cdn_fallback* (default ``False``) must be explicitly enabled.
    When disabled, a cache miss returns ``None`` immediately.

    When *cache_dir* fails the **write probe** (create temp file →
    write → read → delete), the instance sets ``cache_disabled = True``
    and operates without disk persistence.
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        client: Optional[httpx.AsyncClient] = None,
        *,
        cdn_fallback: bool = False,
    ) -> None:
        self.cache_dir = cache_dir or os.path.join(
            tempfile.gettempdir(), "pjsk_jackets",
        )
        self._client = client
        self.cdn_fallback = cdn_fallback
        self.cache_disabled: bool = False

        # 1. Ensure directory exists
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError:
            self.cache_disabled = True
            logger.debug(
                "JacketCache dir creation failed, cache disabled: %s",
                self.cache_dir,
            )
            return

        # 2. Write probe — a dir that exists may still be unwritable
        if not self._probe_writable():
            self.cache_disabled = True
            logger.debug(
                "JacketCache write probe failed, cache disabled: %s",
                self.cache_dir,
            )

    # -- public API --------------------------------------------------------

    async def get_jacket(self, song_id: int) -> str | None:
        """Return the jacket data URL for *song_id*, or ``None``.

        Lookup order:
        1. Local cache (multi-format, priority-then-fallback)
        2. CDN (only when ``cdn_fallback=True``)
        """
        if not self.cache_disabled:
            data_url = await self._load_from_cache(song_id)
            if data_url is not None:
                return data_url

        if self.cdn_fallback:
            async with _FETCH_SEM:
                return await self._fetch_from_cdn(song_id)

        return None

    def get_jacket_file_url(self, song_id: int) -> str | None:
        """Return an HTTP URL for the cached jacket, served by the render service.

        The render service exposes ``GET /jacket/{song_id}`` which reads
        the file from this cache directory and returns it.  Chromium loads
        jackets via HTTP — avoiding both base64 bloat and the ``file://``
        security restriction in ``page.set_content()``.
        """
        if self.cache_disabled:
            return None
        for candidate in _candidate_paths(self.cache_dir, song_id):
            if os.path.isfile(candidate):
                return f"http://127.0.0.1:3000/jacket/{song_id}"
        return None

    async def prefetch_jackets(self, song_ids: list[int]) -> dict[int, str]:
        """Download multiple jackets concurrently.

        Returns a dict mapping each *song_id* to its data URL.
        Songs whose jacket could not be fetched are omitted.
        """

        async def _resolve(sid: int) -> tuple[int, str | None]:
            return sid, await self.get_jacket(sid)

        results = await asyncio.gather(*(_resolve(sid) for sid in song_ids))
        return {sid: data_url for sid, data_url in results if data_url is not None}

    # -- internal ----------------------------------------------------------

    def _canonical_path(self, song_id: int) -> str:
        """Path used for new CDN writes (always .webp)."""
        return os.path.join(self.cache_dir, f"{song_id}.webp")

    def _probe_writable(self) -> bool:
        """Create a temp file, write a byte, read it back, then delete.

        Returns True only if all steps succeed.
        """
        probe_name = ".jacket_cache_write_probe"
        probe_path = os.path.join(self.cache_dir, probe_name)
        try:
            with open(probe_path, "wb") as f:
                f.write(b"\x00")
            with open(probe_path, "rb") as f:
                if f.read(1) != b"\x00":
                    return False
            os.unlink(probe_path)
            return True
        except OSError:
            # Best-effort cleanup
            try:
                os.unlink(probe_path)
            except OSError:
                pass
            return False

    async def _load_from_cache(self, song_id: int) -> str | None:
        """Try each candidate path; first valid image wins.

        Corrupt files (wrong format, truncated) are skipped and
        best-effort deleted.
        """
        for path in _candidate_paths(self.cache_dir, song_id):
            if not os.path.exists(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size < _MIN_FILE_SIZE:
                continue

            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue

            fmt = _detect_format(data)
            if fmt is None:
                logger.debug(
                    "JacketCache: corrupt file skipped — %s (%d bytes)",
                    os.path.basename(path), len(data),
                )
                try:
                    os.unlink(path)
                except OSError:
                    pass
                continue

            return f"data:{_MIME_MAP[fmt]};base64,{base64.b64encode(data).decode()}"

        return None

    async def _fetch_from_cdn(self, song_id: int) -> str | None:
        """Fetch jacket from CDN, validate, cache (if writable), return data URL."""
        url = _build_cdn_url(song_id)
        try:
            if self._client is not None:
                resp = await self._client.get(url, timeout=15.0)
                if resp.status_code != 200:
                    return None
                content = resp.content
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        return None
                    content = resp.content
        except Exception:
            logger.debug("Jacket CDN fetch failed: %d", song_id, exc_info=True)
            return None

        # Content validation
        fmt = _detect_format(content)
        if fmt is None:
            logger.debug(
                "Jacket CDN returned non-image: song_id=%d len=%d",
                song_id, len(content),
            )
            return None

        data_url = (
            f"data:{_MIME_MAP[fmt]};base64,"
            f"{base64.b64encode(content).decode()}"
        )

        # Write-through only when cache is enabled
        if self.cache_disabled:
            return data_url

        path = self._canonical_path(song_id)
        try:
            fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".webp")
            try:
                os.write(fd, content)
            finally:
                os.close(fd)
            os.replace(tmp, path)
            logger.debug("Jacket cached: %d (%d bytes)", song_id, len(content))
        except OSError:
            logger.debug("Jacket cache write failed: %d", song_id)

        return data_url
