"""Tests for render_ocr_card."""
from unittest.mock import AsyncMock, MagicMock

import pytest


class FakeRenderer:
    """Renderer stub that returns preset bytes."""
    def __init__(self, png: bytes | None = b"fake-png") -> None:
        self.png = png
        self.calls: list[object] = []

    async def render(self, payload: object) -> bytes | None:
        self.calls.append(payload)
        return self.png


class TestRenderOcrCard:
    async def test_returns_png_on_success(self) -> None:
        from pjsk_core.application.render_ocr_card import render_ocr_card

        renderer = FakeRenderer(b"card-png-bytes")
        result = await render_ocr_card(
            song_id=1,
            title_ja="テスト曲",
            title_cn="测试曲",
            difficulty="master",
            level=32,
            constant="32.5",
            accuracy=101.0,
            rating=3300.0,
            sp="12345.67",
            perfect=1200, great=0, good=0, bad=0, miss=0,
            status="ap",
            jacket_data_url=None,
            renderer=renderer,
        )

        assert result == b"card-png-bytes"
        assert len(renderer.calls) == 1
        payload = renderer.calls[0]
        assert payload.template_name == "html"
        assert payload.data["width"] == 960
        assert payload.data["height"] == 600
        assert "テスト曲" in payload.data["html"]

    async def test_returns_none_on_renderer_failure(self) -> None:
        from pjsk_core.application.render_ocr_card import render_ocr_card

        renderer = FakeRenderer(None)
        result = await render_ocr_card(
            song_id=1,
            title_ja="Test",
            title_cn="",
            difficulty="expert",
            level=28,
            constant="28.0",
            accuracy=100.5,
            rating=2750.0,
            sp="12000.00",
            perfect=900, great=0, good=0, bad=0, miss=0,
            status="fc",
            jacket_data_url="data:image/png;base64,abc123",
            renderer=renderer,
        )

        assert result is None

    async def test_jacket_in_html_when_provided(self) -> None:
        from pjsk_core.application.render_ocr_card import render_ocr_card

        renderer = FakeRenderer()
        await render_ocr_card(
            song_id=10,
            title_ja="Song",
            title_cn="",
            difficulty="hard",
            level=18,
            constant="",
            accuracy=95.0,
            rating=2000.0,
            sp="—",
            perfect=800, great=100, good=50, bad=10, miss=5,
            status="clear",
            jacket_data_url="data:image/webp;base64,DEADBEEF",
            renderer=renderer,
        )

        html = renderer.calls[0].data["html"]
        assert 'data:image/webp;base64,DEADBEEF' in html
        assert '<div class="jacket">' in html

    async def test_placeholder_when_no_jacket(self) -> None:
        from pjsk_core.application.render_ocr_card import render_ocr_card

        renderer = FakeRenderer()
        await render_ocr_card(
            song_id=10,
            title_ja="Song",
            title_cn="",
            difficulty="hard",
            level=18,
            constant="",
            accuracy=95.0,
            rating=2000.0,
            sp="—",
            perfect=800, great=100, good=50, bad=10, miss=5,
            status="clear",
            jacket_data_url=None,
            renderer=renderer,
        )

        html = renderer.calls[0].data["html"]
        assert "jacket-placeholder" in html

    def test_grade_sss_above_101(self) -> None:
        from pjsk_core.application.render_ocr_card import _get_acc_grade

        label, css = _get_acc_grade(101.0)
        assert label == "SSS+"
        assert css == "rainbow"

    def test_grade_ss_at_100(self) -> None:
        from pjsk_core.application.render_ocr_card import _get_acc_grade

        label, css = _get_acc_grade(100.0)
        assert label == "SS"
        assert css == "ss"

    def test_grade_a_at_98(self) -> None:
        from pjsk_core.application.render_ocr_card import _get_acc_grade

        label, css = _get_acc_grade(98.5)
        assert label == "A"
        assert css == "a"

    def test_grade_d_below_90(self) -> None:
        from pjsk_core.application.render_ocr_card import _get_acc_grade

        label, css = _get_acc_grade(85.0)
        assert label == "D"
        assert css == "d"

    def test_grade_sss_between_100_75_and_101(self) -> None:
        from pjsk_core.application.render_ocr_card import _get_acc_grade

        label, _ = _get_acc_grade(100.8)
        assert label == "SSS"

    def test_build_status_ap(self) -> None:
        from pjsk_core.application.render_ocr_card import _build_status_html

        html = _build_status_html("ap")
        assert "ALL PERFECT" in html
        assert "badge-ap" in html

    def test_build_status_fc(self) -> None:
        from pjsk_core.application.render_ocr_card import _build_status_html

        html = _build_status_html("fc")
        assert "FULL COMBO" in html
        assert "badge-fc" in html

    def test_build_status_clear(self) -> None:
        from pjsk_core.application.render_ocr_card import _build_status_html

        html = _build_status_html("clear")
        assert "CLEAR" in html
        assert "badge-clear" in html

    def test_build_grade_rainbow(self) -> None:
        from pjsk_core.application.render_ocr_card import _build_grade_html

        html = _build_grade_html("SSS+", "rainbow")
        assert "grade-rainbow" in html
        assert "SSS+" in html

    def test_build_grade_solid(self) -> None:
        from pjsk_core.application.render_ocr_card import _build_grade_html

        html = _build_grade_html("SS", "ss")
        assert "grade-solid" in html
        assert "SS" in html
        assert "#4c80f0" in html
