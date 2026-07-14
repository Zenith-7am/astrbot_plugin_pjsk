"""Tests for jacket cache adapter — CDN fetch + local disk cache."""

import base64
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jackets"
    d.mkdir()
    return d


# A fake "WebP" payload — must be ≥100 bytes to pass _MIN_FILE_SIZE check.
# Real WebP files are >100 bytes; this is just test padding.
_WEBP_PAYLOAD = b"RIFF$\x00\x00\x00WEBPVP8 \x1a\x00\x00\x00" + b"\x00" * 80


def _b64_image(data: bytes) -> str:
    return f"data:image/webp;base64,{base64.b64encode(data).decode()}"


class TestJacketCache:
    """Core contract: get_jacket returns data URL or None."""

    async def test_load_from_cache_hit(self, cache_dir: Path) -> None:
        """When a cached file exists on disk, return it without CDN call."""
        from adapters.rendering.jacket_cache import JacketCache

        # Pre-populate cache file
        cached = cache_dir / "42.webp"
        cached.write_bytes(_WEBP_PAYLOAD)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result == _b64_image(_WEBP_PAYLOAD)

    async def test_cache_miss_fetches_from_cdn(self, cache_dir: Path) -> None:
        """When no cache exists, fetch from CDN and cache to disk."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _WEBP_PAYLOAD
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        assert result == _b64_image(_WEBP_PAYLOAD)
        # Should have been cached to disk
        assert (cache_dir / "42.webp").exists()

    async def test_cdn_fetch_returns_none_on_404(self, cache_dir: Path) -> None:
        """CDN 404 → return None, don't cache."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.content = b""
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(999)

        assert result is None
        assert not (cache_dir / "999.webp").exists()

    async def test_cdn_error_returns_none(self, cache_dir: Path) -> None:
        """CDN network error → return None gracefully."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=OSError("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        assert result is None

    async def test_prefetch_jackets_batch(self, cache_dir: Path) -> None:
        """prefetch_jackets downloads multiple jackets concurrently."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _WEBP_PAYLOAD
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.prefetch_jackets([1, 2, 3])

        assert isinstance(result, dict)
        assert result[1] == _b64_image(_WEBP_PAYLOAD)
        assert result[2] == _b64_image(_WEBP_PAYLOAD)
        assert result[3] == _b64_image(_WEBP_PAYLOAD)
        # All cached
        assert (cache_dir / "1.webp").exists()
        assert (cache_dir / "2.webp").exists()
        assert (cache_dir / "3.webp").exists()

    async def test_default_cache_dir(self) -> None:
        """Default cache dir is tempdir when not specified."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache()
        assert jc.cache_dir is not None
        assert os.path.isdir(jc.cache_dir)

    async def test_song_id_zero_padding_not_used(self, cache_dir: Path) -> None:
        """song_id is used as-is (no zero-padding)."""
        from adapters.rendering.jacket_cache import JacketCache

        # Pre-populate cache with non-padded name
        cached = cache_dir / "42.webp"
        cached.write_bytes(_WEBP_PAYLOAD)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None

    async def test_empty_file_returned_as_none(self, cache_dir: Path) -> None:
        """Corrupt/empty cache file → re-fetch from CDN (returns None if CDN also fails)."""
        from adapters.rendering.jacket_cache import JacketCache

        # Write empty cache file
        cached = cache_dir / "42.webp"
        cached.write_bytes(b"")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=OSError("no network"))

        jc = JacketCache(cache_dir=str(cache_dir))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        # Empty cache is rejected, CDN fails → None
        assert result is None
