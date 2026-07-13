"""Tests for ReplyBuilder."""
from pjsk_emubot.reply_builder import PluginErrorCode, ReplyBuilder


class TestReplyBuilder:
    def test_text_returns_plain_component(self) -> None:
        result = ReplyBuilder.text("Hello")
        assert len(result) == 1
        assert result[0].text == "Hello"

    def test_error_success_returns_not_confirmable(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.SUCCESS)
        assert len(result) == 1
        assert "已记录" in result[0].text

    def test_error_all_engines_down(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.ALL_ENGINES_DOWN)
        assert "暂不可用" in result[0].text

    def test_error_not_pjsk_screenshot(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.NOT_PJSK_SCREENSHOT)
        assert "未能识别" in result[0].text

    def test_error_rate_limited(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.USER_RATE_LIMITED)
        assert "人数较多" in result[0].text

    def test_error_image_too_large(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.IMAGE_TOO_LARGE)
        assert "过大" in result[0].text

    def test_error_multiple_images(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.MULTIPLE_IMAGES)
        assert "只能识别一张" in result[0].text

    def test_error_ocr_timeout(self) -> None:
        result = ReplyBuilder.error(PluginErrorCode.OCR_TIMEOUT)
        assert "超时" in result[0].text


class TestPluginErrorCode:
    def test_all_codes_have_unique_values(self) -> None:
        values = [e.value for e in PluginErrorCode]
        assert len(values) == len(set(values))
