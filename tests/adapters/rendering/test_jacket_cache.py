"""Tests for jacket cache adapter — multi-format read, write probe, CDN opt-in."""

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


# ── Test payloads ────────────────────────────────────────────────────────

_VALID_WEBP = (
    b"RIFF\x5a\x00\x00\x00WEBPVP8 \x1a\x00\x00\x00"  # 20-byte header
    + b"\x00" * 90
)

# Minimal valid PNG (1×1 pixel, gray)
_VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    + b"\x00" * 40  # pad to ≥100 bytes
)

# Minimal valid JPEG (1×1 pixel, gray)
_VALID_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09"
    b"\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c\x20\x24\x2e\x27\x20\x22\x2c\x23\x1c\x1c"
    b"\x28\x37\x29\x2c\x30\x31\x34\x34\x34\x1f\x27\x39\x3d\x38\x32\x3c"
    b"\x2e\x33\x34\x32\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11"
    b"\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
    b"\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05"
    b"\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06"
    b"\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3b"
    b"\x09\xc1\x16\x17\x18\x19\x1a%\x26'()*456789:CDEFGHIJSTUVWXYZ"
    b"\xc4\xa3\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\x00\xff\xd9"
)

_HTML_PAYLOAD = b"<!DOCTYPE html><html><body>404 Not Found</body></html>" + b"\x00" * 50

_TRUNCATED_RIFF = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10

# Valid-looking WebP header but with garbage body (passes signature, fails size)
_SHORT_WEBP = b"RIFF\x04\x00\x00\x00WEBP\x00\x00\x00\x00"


def _b64(data: bytes, mime: str = "image/webp") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


# ── Existing: cache hit / CDN behaviour (CDN is now opt-in) ─────────────


class TestJacketCache:
    """Core contract: get_jacket returns data URL or None."""

    async def test_load_from_cache_hit(self, cache_dir: Path) -> None:
        """When a cached .webp file exists, return it without CDN call."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.webp").write_bytes(_VALID_WEBP)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result == _b64(_VALID_WEBP, "image/webp")

    async def test_cache_miss_no_cdn_by_default(self, cache_dir: Path) -> None:
        """CDN fallback is OFF by default → cache miss returns None."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is None

    async def test_cache_miss_with_cdn_fallback(self, cache_dir: Path) -> None:
        """cdn_fallback=True → cache miss fetches from CDN and caches to disk."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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

        assert result == _b64(_VALID_WEBP, "image/webp")
        assert (cache_dir / "42.webp").exists()

    async def test_cdn_fetch_returns_none_on_404(self, cache_dir: Path) -> None:
        """CDN 404 → return None, don't cache."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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
        assert result[1] == _b64(_VALID_WEBP, "image/webp")
        assert result[2] == _b64(_VALID_WEBP, "image/webp")
        assert result[3] == _b64(_VALID_WEBP, "image/webp")
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
        """song_id is used as-is for .webp (canonical format)."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.webp").write_bytes(_VALID_WEBP)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None

    async def test_cdn_fallback_default_is_false(self) -> None:
        """CDN fallback is opt-in — constructor default is False."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache()
        assert jc.cdn_fallback is False


# ── Multi-format loading (PNG / JPEG / WebP) ─────────────────────────────


class TestMultiFormatLoading:
    """JacketCache reads PNG, JPEG, and WebP; emits correct MIME type."""

    async def test_load_png_from_cache(self, cache_dir: Path) -> None:
        """PNG file on disk → correct image/png MIME in data URL."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.webp").write_bytes(_VALID_PNG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    async def test_load_jpeg_from_cache(self, cache_dir: Path) -> None:
        """JPEG file on disk → correct image/jpeg MIME in data URL."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.webp").write_bytes(_VALID_JPEG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    async def test_load_webp_from_cache(self, cache_dir: Path) -> None:
        """WebP file on disk → correct image/webp MIME in data URL."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.webp").write_bytes(_VALID_WEBP)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/webp;base64,")


# ── Legacy filename patterns (old cache layout) ──────────────────────────


class TestLegacyFilenamePatterns:
    """JacketCache resolves old naming conventions from the emu-bot era."""

    async def test_load_zero_padded_png(self, cache_dir: Path) -> None:
        """jacket_s_042.png (very old format) → song_id 42."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "jacket_s_042.png").write_bytes(_VALID_PNG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    async def test_load_zero_padded_jpg(self, cache_dir: Path) -> None:
        """042.jpg (old zero-padded JPG) → song_id 42."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "042.jpg").write_bytes(_VALID_JPEG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    async def test_load_plain_jpg(self, cache_dir: Path) -> None:
        """42.jpg (plain JPG) → song_id 42."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.jpg").write_bytes(_VALID_JPEG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    async def test_load_zero_padded_png_plain_name(self, cache_dir: Path) -> None:
        """042.png (zero-padded PNG) → song_id 42."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "042.png").write_bytes(_VALID_PNG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    async def test_webp_preferred_over_legacy(self, cache_dir: Path) -> None:
        """When both 42.webp and 042.jpg exist, prefer .webp (canonical format)."""
        from adapters.rendering.jacket_cache import JacketCache

        (cache_dir / "42.webp").write_bytes(_VALID_WEBP)
        (cache_dir / "042.jpg").write_bytes(_VALID_JPEG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/webp;base64,")

    async def test_fallback_to_next_candidate_on_corrupt(self, cache_dir: Path) -> None:
        """.webp file is corrupt → skip to next candidate (042.jpg)."""
        from adapters.rendering.jacket_cache import JacketCache

        # Corrupt .webp (wrong content)
        (cache_dir / "42.webp").write_bytes(_HTML_PAYLOAD)
        # Valid legacy JPEG as fallback
        (cache_dir / "042.jpg").write_bytes(_VALID_JPEG)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")


# ── WebP content validation (CDN fetch path) ─────────────────────────────


class TestWebPValidation:
    """CDN responses must be valid WebP images, not HTML error pages etc."""

    async def test_valid_webp_cached(self, cache_dir: Path) -> None:
        """RIFF....WEBP header → content is cached and returned."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

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

        jc = JacketCache(cache_dir=str(cache_dir), cdn_fallback=True)

        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.content = _VALID_WEBP
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

    def test_file_in_place_of_dir_disables_cache(self, tmp_path: Path) -> None:
        """Constructor sets cache_disabled = True when dir creation fails."""
        from adapters.rendering.jacket_cache import JacketCache

        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")

        jc = JacketCache(cache_dir=str(blocked))
        assert jc.cache_disabled is True

    def test_cache_disabled_false_when_writable(self, cache_dir: Path) -> None:
        """Normal writable dir → cache_disabled = False."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))
        assert jc.cache_disabled is False

    async def test_disabled_cache_skips_read_and_write(self, tmp_path: Path) -> None:
        """cache_disabled=True → skip disk entirely, still return data from CDN."""
        from adapters.rendering.jacket_cache import JacketCache

        blocked = tmp_path / "blocked_cache"
        blocked.write_text("not a directory")

        jc = JacketCache(cache_dir=str(blocked), cdn_fallback=True)
        assert jc.cache_disabled is True

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


# ── Write probe ──────────────────────────────────────────────────────────


class TestWriteProbe:
    """Real write probe catches dirs that exist but aren't writable."""

    def test_dir_exists_but_not_writable_probe_catches(self, tmp_path: Path) -> None:
        """Write probe fails when open(..., 'wb') raises OSError."""
        from adapters.rendering.jacket_cache import JacketCache

        ro_dir = tmp_path / "readonly_dir"
        ro_dir.mkdir()

        # Patch open() so that the write probe fails with OSError.
        # This is the cross-platform equivalent of an unwritable dir.
        import builtins
        _real_open = builtins.open

        def _failing_open(file, mode="r", *args, **kwargs):
            path = str(file)
            if "w" in mode and ".jacket_cache_write_probe" in path:
                raise OSError("Permission denied")
            return _real_open(file, mode, *args, **kwargs)

        with patch("builtins.open", _failing_open):
            jc = JacketCache(cache_dir=str(ro_dir))

        assert jc.cache_disabled is True

    def test_write_probe_passes_on_writable_dir(self, cache_dir: Path) -> None:
        """Normal writable dir → probe passes, cache_disabled = False."""
        from adapters.rendering.jacket_cache import JacketCache

        jc = JacketCache(cache_dir=str(cache_dir))
        assert jc.cache_disabled is False


# ── Corrupt file detection and cleanup ───────────────────────────────────


class TestCorruptFileCleanup:
    """Valid extension, invalid content → skip + best-effort unlink."""

    async def test_corrupt_webp_skipped_and_deleted(self, cache_dir: Path) -> None:
        """.webp file with HTML content → skip, try to delete."""
        from adapters.rendering.jacket_cache import JacketCache

        corrupt_path = cache_dir / "42.webp"
        corrupt_path.write_bytes(_HTML_PAYLOAD)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)

        # Corrupt file is skipped → None (no CDN fallback)
        assert result is None
        # Best-effort deletion: file should be gone
        assert not corrupt_path.exists()

    async def test_corrupt_png_skipped_and_deleted(self, cache_dir: Path) -> None:
        """PNG filename but content is not PNG → skip + delete."""
        from adapters.rendering.jacket_cache import JacketCache

        corrupt_path = cache_dir / "42.webp"  # webp extension, but contains junk
        corrupt_path.write_bytes(b"not an image" * 10)

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)

        assert result is None
        assert not corrupt_path.exists()

    async def test_empty_file_no_unlink_attempt(self, cache_dir: Path) -> None:
        """Empty file is below MIN_FILE_SIZE → skip without trying to unlink."""
        from adapters.rendering.jacket_cache import JacketCache

        empty_path = cache_dir / "42.webp"
        empty_path.write_bytes(b"")

        jc = JacketCache(cache_dir=str(cache_dir))
        result = await jc.get_jacket(42)

        assert result is None
        # Empty file is skipped early (size check), no unlink attempted.
        # We don't care if it's still there — just that we didn't crash.
