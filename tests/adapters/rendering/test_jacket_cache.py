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


# A valid WebP payload — RIFF signature + WEBP fourcc + VP8 chunk header.
# Must be ≥100 bytes to pass _MIN_FILE_SIZE check.
_VALID_WEBP = (
    b"RIFF\x5a\x00\x00\x00WEBPVP8 \x1a\x00\x00\x00"  # 20-byte header
    + b"\x00" * 90                                     # padding to ≥100 bytes
)

# NOT a WebP — HTML error page (common CDN failure mode)
_HTML_PAYLOAD = b"<!DOCTYPE html><html><body>404 Not Found</body></html>" + b"\x00" * 50

# Truncated RIFF header — starts right but too short
_TRUNCATED_RIFF = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10  # only ~26 bytes


def _b64_image(data: bytes) -> str:
    return f"data:image/webp;base64,{base64.b64encode(data).decode()}"


class TestJacketCache:
    """Core contract: get_jacket returns data URL or None."""

    async def test_load_from_cache_hit(self, cache_dir: Path) -> None:
        """When a cached file exists on disk, return it without CDN call."""
        from adapters.rendering.jacket_cache import JacketCache

        # Pre-populate cache file
        cached = cache_dir / "42.webp"
        cached.write_bytes(_VALID_WEBP)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result == _b64_image(_VALID_WEBP)

    async def test_cache_miss_fetches_from_cdn(self, cache_dir: Path) -> None:
        """When no cache exists, fetch from CDN and cache to disk."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _VALID_WEBP
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        assert result == _b64_image(_VALID_WEBP)
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
        mock_response.content = _VALID_WEBP
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.prefetch_jackets([1, 2, 3])

        assert isinstance(result, dict)
        assert result[1] == _b64_image(_VALID_WEBP)
        assert result[2] == _b64_image(_VALID_WEBP)
        assert result[3] == _b64_image(_VALID_WEBP)
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
        cached.write_bytes(_VALID_WEBP)

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


# ── WebP content validation ──────────────────────────────────────────────


class TestWebPValidation:
    """CDN responses must be valid WebP images, not HTML error pages etc."""

    async def test_valid_webp_cached(self, cache_dir: Path) -> None:
        """RIFF....WEBP header → content is cached and returned."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _VALID_WEBP
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        assert result is not None
        assert result.startswith("data:image/webp;base64,")
        assert (cache_dir / "42.webp").exists()

    async def test_html_response_rejected(self, cache_dir: Path) -> None:
        """CDN returns HTML error page → not cached, returns None."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _HTML_PAYLOAD
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        assert result is None
        assert not (cache_dir / "42.webp").exists()

    async def test_truncated_webp_rejected(self, cache_dir: Path) -> None:
        """CDN returns truncated data → not cached, returns None."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _TRUNCATED_RIFF
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        assert result is None
        assert not (cache_dir / "42.webp").exists()

    async def test_non_200_skips_validation(self, cache_dir: Path) -> None:
        """HTTP 404 → returns None before content validation (no cache write)."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))

        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.content = _VALID_WEBP  # valid bytes but wrong status
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


# ── Cache directory unwritable → graceful degradation ───────────────────


class TestCacheDirUnwritable:
    """When cache_dir is unwritable, JacketCache disables writes, not crash."""

    def test_cache_disabled_property(self, tmp_path: Path) -> None:
        """Constructor sets cache_disabled = True when dir creation fails."""
        from adapters.rendering.jacket_cache import JacketCache

        # Create a FILE where the directory should be — os.makedirs will
        # raise FileExistsError (an OSError subclass) on any platform.
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")

        jc = JacketCache(cache_dir=str(blocked))
        assert jc.cache_disabled is True

    def test_cache_disabled_false_when_writable(self, cache_dir: Path) -> None:
        """Normal writable dir → cache_disabled = False."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))
        assert jc.cache_disabled is False

    async def test_disabled_cache_skips_write(self, tmp_path: Path) -> None:
        """When cache_disabled=True, CDN fetch still returns data URL
        but does not attempt to write to disk."""
        from adapters.rendering.jacket_cache import JacketCache

        blocked = tmp_path / "blocked_cache"
        blocked.write_text("not a directory")

        jc = JacketCache(cache_dir=str(blocked))
        assert jc.cache_disabled is True

        # CDN fetch should still work — just no cache write
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = _VALID_WEBP
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await jc.get_jacket(42)

        # Still returns the data URL (graceful degradation)
        assert result is not None
        assert result.startswith("data:image/webp;base64,")
