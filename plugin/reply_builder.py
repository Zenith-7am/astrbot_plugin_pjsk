"""ReplyBuilder — convert domain results to AstrBot message chains."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PluginErrorCode(Enum):
    """Internal error codes — never shown to users."""
    SUCCESS = "success"
    ALL_ENGINES_DOWN = "all_engines_down"
    NOT_PJSK_SCREENSHOT = "not_pjsk_screenshot"
    OCR_TIMEOUT = "ocr_timeout"
    IMAGE_TOO_LARGE = "image_too_large"
    MULTIPLE_IMAGES = "multiple_images"
    USER_RATE_LIMITED = "user_rate_limited"


_MESSAGES = {
    PluginErrorCode.SUCCESS: "已记录",
    PluginErrorCode.ALL_ENGINES_DOWN: "识别服务暂不可用，请稍后再试",
    PluginErrorCode.NOT_PJSK_SCREENSHOT: "未能识别到 PJSK 成绩，请确认截图正确",
    PluginErrorCode.OCR_TIMEOUT: "识别超时，请稍后重试",
    PluginErrorCode.IMAGE_TOO_LARGE: "图片过大，请压缩后重试",
    PluginErrorCode.MULTIPLE_IMAGES: "目前一次只能识别一张",
    PluginErrorCode.USER_RATE_LIMITED: "当前使用人数较多，请稍后再试",
}


@dataclass
class _FakePlainText:
    """Stand-in for astrbot.api.message_components.Plain."""
    text: str
    type: str = "plain"


class ReplyBuilder:
    """Build AstrBot message chains from plugin results.

    Uses fake Plain component type that matches AstrBot's wire format.
    When running inside a real AstrBot instance, the framework's
    Plain/Image components are used instead via monkey-patch or
    import-time detection.
    """

    @staticmethod
    def text(plain_text: str) -> list[Any]:
        return [_FakePlainText(text=plain_text)]

    @staticmethod
    def error(code: PluginErrorCode) -> list[Any]:
        msg = _MESSAGES.get(code, "未知错误")
        return [_FakePlainText(text=msg)]
