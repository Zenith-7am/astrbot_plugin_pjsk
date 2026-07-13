"""PjskPlugin -- AstrBot Star plugin with OCR recognition and candidate confirmation.

Testable helper functions are at module level:
* ``_image_count(event)`` -- count Image components in the event message.
* ``_handle_image(event, rt)`` -- OCR recognition flow for incoming images.
* ``_handle_selection(text, user_id, conversation_id, rt)`` -- candidate confirmation.
* ``_is_at_bot(event)`` -- check if the event message @mentions the bot.
* ``_is_group_chat(event)`` -- check if the event is from a group chat.
"""
from __future__ import annotations

import logging
from typing import Any

from plugin.candidate_presenter import CandidatePresenter
from plugin.event_mapper import EventMapper
from plugin.reply_builder import PluginErrorCode, ReplyBuilder
from plugin.runtime import PluginRuntime
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import CandidateSet as _CandidateSet

_logger = logging.getLogger(__name__)

# ── AstrBot imports (correct paths) ──────────────────────────────────────────
try:
    from astrbot.api.event import filter, AstrMessageEvent  # noqa: F401
    from astrbot.api.star import Context, Star, register  # noqa: F401
    from astrbot.api import logger  # noqa: F401
except ImportError:
    # Dev/testing fallback — filter becomes a mock with no-op decorators
    class _FakeFilter:
        """Mock filter that returns no-op decorators for dev/testing."""

        class EventMessageType:
            ALL = "all"

        @staticmethod
        def command(name: str) -> Any:  # noqa: ARG004
            return lambda fn: fn

        @staticmethod
        def event_message_type(etype: str) -> Any:  # noqa: ARG004
            return lambda fn: fn

    filter = _FakeFilter()
    AstrMessageEvent = object
    Context = object
    Star = object
    logger = logging.getLogger("astrbot")

    def register(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        """No-op register decorator for dev/testing."""
        return lambda cls: cls


# ── Helper functions (testable with fakes) ───────────────────────────────────


def _image_count(event: Any) -> int:
    """Count Image components in an AstrBot event message.

    Uses class-name duck-typing so no AstrBot types are imported at
    runtime.  AstrBot's ``Image`` component has ``__class__.__name__``
    of ``"Image"``.
    """
    return sum(
        1 for c in event.message_obj.message
        if c.__class__.__name__ == "Image"
    )


def _is_at_bot(event: Any) -> bool:
    """Check if the event message contains an @Bot mention."""
    return any(
        c.__class__.__name__ == "At" for c in event.message_obj.message
    )


def _is_group_chat(event: Any) -> bool:
    """Check if the event is from a group chat (not private)."""
    return event.get_group_id() is not None


async def _handle_image(event: Any, rt: PluginRuntime) -> PluginErrorCode:
    """Process incoming image for OCR score recognition.

    Flow
    ----
    1. Count images -- reject 0 or >1 immediately.
    2. Extract image context via ``EventMapper``.
    3. Auto-register user if they do not exist yet.
    4. Rate-limit check (in-memory per-user cooldown).
    5. Run ``RecognizeScore`` use case.
    6. Return result code.
    """
    count = _image_count(event)
    if count == 0:
        return PluginErrorCode.NOT_PJSK_SCREENSHOT
    if count > 1:
        return PluginErrorCode.MULTIPLE_IMAGES

    mapper = EventMapper()
    ctx = mapper.extract(event)
    if ctx is None:
        return PluginErrorCode.NOT_PJSK_SCREENSHOT

    # QQ Official Bot: sender_id is OpenID, not QQ number
    if mapper.is_qq_official(event):
        # OpenID flow — first version requires bind
        return PluginErrorCode.QQ_OFFICIAL_NEEDS_BIND

    # Auto-register: ensure user exists
    user = await rt.user_repo.get_by_qq(ctx.qq_number)
    if user is None:
        user = await rt.user_repo.create(ctx.qq_number, game_id=None)

    # Rate limit check
    if not rt.rate_limiter.check(user.id):
        return PluginErrorCode.USER_RATE_LIMITED
    rt.rate_limiter.mark(user.id)

    result = await rt.recognize_score.recognize(
        user.id, ctx.image_bytes, source_gateway=ctx.source_gateway,
    )

    if result.score_attempt is not None:
        return PluginErrorCode.SUCCESS

    if result.candidates_for_user:
        cid = result.candidate_set_id
        if cid is not None:
            conv_id = mapper.extract_conversation_id(event)
            display_cs = _CandidateSet(
                candidates=result.candidates_for_user,
                image_sha256="", source_gateway="",
                ocr_run_id=0, chart_data_version="",
            )
            display_text = CandidatePresenter.format(display_cs, cid)
            rt.set_pending(user.id.value, conv_id, cid, display_text)
        return PluginErrorCode.CANDIDATES_AVAILABLE

    return PluginErrorCode.NOT_PJSK_SCREENSHOT


async def _handle_selection(
    text: str,
    user_id: UserId,
    conversation_id: str,
    rt: PluginRuntime,
) -> tuple[bool, str | None]:
    """Try to consume user input as a candidate selection.

    Returns ``(is_selection, error_message)``:
    - ``(False, None)`` — not a selection; passthrough to chat personality
    - ``(True, None)`` — confirmed successfully
    - ``(True, "...")`` — selection detected but failed (invalid index, expired, etc.)
    """
    import re
    text = text.strip()

    cid = rt.get_pending_candidate_set_id(user_id.value, conversation_id)
    if cid is None:
        return False, None

    selection: int | None = None

    # Priority: explicit "选 <id> <num>" format
    m = re.match(r'选\s+(\S+)\s+(\d+)', text)
    if m:
        matched_cid, num = m.group(1), int(m.group(2))
        if matched_cid == cid:
            selection = num

    # Priority: pure number
    if selection is None:
        try:
            selection = int(text)
        except ValueError:
            return False, None  # Not a selection at all

    result = await rt.confirm_candidate.confirm(
        user_id, cid, selection,
    )
    if result.error is not None:
        return True, f"确认失败：{result.error.value}"
    # Success — clean up pending
    rt.clear_pending(user_id.value, conversation_id)
    return True, None


# ── AstrBot Plugin class ─────────────────────────────────────────────────────


@register(
    "pjsk-astrbot",
    "leoviria",
    "PJSK score tracking, B20, and chart rankings via multi-model vision OCR",
    "0.0.0",
)
class PjskPlugin(Star):  # type: ignore
    """PJSK score recognition plugin for AstrBot."""

    def __init__(self, context: Any) -> None:
        super().__init__(context)
        self._runtime: PluginRuntime | None = None

    # ── Command group placeholder ─────────────────────────────────────────
    @filter.command("pjsk")  # type: ignore
    async def pjsk_command_group(self, event: Any) -> None:  # type: ignore
        """``/pjsk`` command group placeholder — sub-commands registered below."""
        yield event.plain_result(
            "PJSK 插件命令：\n"
            "/pjsk bind <游戏ID> — 绑定 PJSK 游戏 ID\n"
            "/pjsk help — 查看帮助"
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────
    async def initialize(self) -> None:
        """Called by AstrBot after plugin instantiation."""
        from pathlib import Path
        from plugin.bootstrap import assemble_plugin_runtime

        conf = getattr(self, "config", {})
        if isinstance(conf, dict):
            db_path_str = conf.get("pjsk_db_path", "data/pjsk.db")
        else:
            db_path_str = "data/pjsk.db"
        self._runtime = await assemble_plugin_runtime(Path(db_path_str))
        _logger.info("PJSK plugin runtime initialized")

    # ── Main message handler ──────────────────────────────────────────────
    @filter.event_message_type(filter.EventMessageType.ALL)  # type: ignore
    async def on_message(self, event: Any) -> None:  # type: ignore
        """Handle incoming messages — candidate selection, image recognition."""
        if self._runtime is None:
            return

        rt = self._runtime
        mapper = EventMapper()

        # ── Candidate selection ───────────────────────────────────────
        if _image_count(event) == 0:
            try:
                text = event.message_obj.message_str or ""
            except (AttributeError, TypeError):
                text = ""
            if text.strip():
                qq = mapper.extract_qq(event)
                user = await rt.user_repo.get_by_qq(qq)
                if user is not None:
                    conv_id = mapper.extract_conversation_id(event)
                    cid = rt.get_pending_candidate_set_id(
                        user.id.value, conv_id,
                    )
                    if cid is not None:
                        is_selection, err_msg = await _handle_selection(
                            text, user.id, conv_id, rt,
                        )
                        if is_selection:
                            if err_msg is not None:
                                yield event.plain_result(err_msg)
                            else:
                                yield event.plain_result("已确认成绩")
                            event.stop_event()
                            return
            # Not a valid selection → fall through to passthrough
            return  # Passthrough to AstrBot personality

        # ── Image handling ────────────────────────────────────────────
        img_count = _image_count(event)
        if img_count > 0:
            # Group chat: require @Bot + Image in same message
            if _is_group_chat(event):
                if not _is_at_bot(event):
                    return  # Plain group image — ignore
                if img_count > 1:
                    yield event.plain_result("目前一次只能识别一张")
                    event.stop_event()
                    return

            code = await _handle_image(event, rt)

            if code == PluginErrorCode.NOT_PJSK_SCREENSHOT:
                return  # Passthrough — not a PJSK screenshot

            if code == PluginErrorCode.QQ_OFFICIAL_NEEDS_BIND:
                yield event.plain_result(
                    "QQ 官方 Bot 暂不支持直接识别，请先用 /pjsk bind 绑定 QQ 号"
                )
                event.stop_event()
                return

            if code == PluginErrorCode.CANDIDATES_AVAILABLE:
                qq = mapper.extract_qq(event)
                user = await rt.user_repo.get_by_qq(qq)
                if user is not None:
                    conv_id = mapper.extract_conversation_id(event)
                    display = rt.get_pending_display_text(
                        user.id.value, conv_id,
                    )
                    if display is not None:
                        yield event.plain_result(display)
                    else:
                        yield ReplyBuilder.error_text(PluginErrorCode.SUCCESS)
            elif code != PluginErrorCode.SUCCESS:
                yield event.plain_result(ReplyBuilder.error_text(code))
            else:
                yield event.plain_result(ReplyBuilder.error_text(PluginErrorCode.SUCCESS))

            event.stop_event()
            return

        # ── Passthrough ───────────────────────────────────────────────
        # Not an image, not a candidate selection → AstrBot personality

    async def terminate(self) -> None:
        """Clean up plugin resources."""
        if self._runtime:
            await self._runtime.close()
            self._runtime = None
