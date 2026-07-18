"""Tests for PNG→JPEG conversion utility."""
import io

from PIL import Image


class TestPngToJpeg:
    def test_converts_and_reduces_size(self) -> None:
        from gateway.adapters.image_utils import png_to_jpeg

        # Create a realistic render-sized image (960×600, OCR card size)
        # PNG of flat color is tiny, so add noise for realistic test
        import random
        random.seed(42)
        img = Image.new("RGB", (960, 600))
        pixels = img.load()
        for y in range(600):
            for x in range(960):
                r = (x * y + random.randint(0, 40)) % 256
                g = (y * 3 + random.randint(0, 30)) % 256
                b = (x * 5 + random.randint(0, 50)) % 256
                pixels[x, y] = (r, g, b)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png = buf.getvalue()
        jpg = png_to_jpeg(png, quality=85)
        assert jpg is not None
        # JPEG should be smaller than PNG for a photographic-style image
        assert len(jpg) < len(png), f"PNG={len(png)} JPEG={len(jpg)}"
        # Verify it's valid JPEG
        jpg_img = Image.open(io.BytesIO(jpg))
        assert jpg_img.format == "JPEG"

    def test_handles_rgba_input(self) -> None:
        from gateway.adapters.image_utils import png_to_jpeg

        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        jpg = png_to_jpeg(buf.getvalue(), quality=85)
        assert jpg is not None
        jpg_img = Image.open(io.BytesIO(jpg))
        assert jpg_img.format == "JPEG"

    def test_returns_none_for_invalid_input(self) -> None:
        from gateway.adapters.image_utils import png_to_jpeg

        assert png_to_jpeg(b"not an image", quality=85) is None

    def test_quality_lower_produces_smaller_file(self) -> None:
        from gateway.adapters.image_utils import png_to_jpeg

        img = Image.new("RGB", (300, 200), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png = buf.getvalue()
        jpg_high = png_to_jpeg(png, quality=90)
        jpg_low = png_to_jpeg(png, quality=30)
        assert jpg_high is not None
        assert jpg_low is not None
        assert len(jpg_low) < len(jpg_high)
