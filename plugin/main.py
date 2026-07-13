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


def _is_at_bot(event: Any, bot_self_id: str = "") -> bool:
    """Check if the event message @mentions the bot specifically.

    If ``bot_self_id`` is empty, falls back to checking for any At
    component (best-effort). When available, only matches At components
    whose ``target`` or ``qq`` attribute equals the bot's self_id.
    """
    for c in event.message_obj.message:
        if c.__class__.__name__ != "At":
            continue
        if not bot_self_id:
            return True  # best-effort: any At counts
        target = getattr(c, "target", "") or getattr(c, "qq", "")
        if str(target) == str(bot_self_id):
            return True
    return False


def _is_group_chat(event: Any) -> bool:
    """Check if the event is from a group chat (not private)."""
    return event.get_group_id() is not None


def _get_self_id(event: Any) -> str:
    """Get the bot's own ID from the event, or empty string."""
    try:
        return str(event.get_self_id() or "")
    except (AttributeError, TypeError):
        return ""


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


def _read_single_image_bytes(event: Any) -> bytes | None:
    """Read the first image from an event as raw bytes."""
    for c in event.message_obj.message:
        if c.__class__.__name__ == "Image":
            if hasattr(c, "file") and c.file:
                import os
                if os.path.isfile(c.file):
                    with open(c.file, "rb") as f:
                        return f.read()
            if hasattr(c, "url") and c.url:
                return None  # URL images need async client — handled in _handle_image
    return None


async def _handle_buffered_image(event: Any, rt: PluginRuntime, image_bytes: bytes) -> PluginErrorCode:
    """Run OCR on buffered image bytes (from EphemeralImageBuffer)."""
    mapper = EventMapper()
    if mapper.is_qq_official(event):
        return PluginErrorCode.QQ_OFFICIAL_NEEDS_BIND
    qq = mapper.extract_qq(event)
    user = await rt.user_repo.get_by_qq(qq)
    if user is None:
        user = await rt.user_repo.create(qq, game_id=None)
    if not rt.rate_limiter.check(user.id):
        return PluginErrorCode.USER_RATE_LIMITED
    rt.rate_limiter.mark(user.id)
    gateway = mapper._gateway_name(event.get_platform_id())
    result = await rt.recognize_score.recognize(
        user.id, image_bytes, source_gateway=gateway,
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


async def _get_image_result_text(event: Any, code: PluginErrorCode, rt: PluginRuntime, mapper: EventMapper) -> str:
    """Get the appropriate reply text for an image recognition result."""
    if code == PluginErrorCode.CANDIDATES_AVAILABLE:
        qq = mapper.extract_qq(event)
        user = await rt.user_repo.get_by_qq(qq)
        if user is not None:
            conv_id = mapper.extract_conversation_id(event)
            display = rt.get_pending_display_text(user.id.value, conv_id)
            if display is not None:
                return display
    return ReplyBuilder.error_text(code)


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

    # ── Commands ─────────────────────────────────────────────────────────
    @filter.command("pjsk")  # type: ignore
    async def pjsk_command_group(self, event: Any) -> None:  # type: ignore
        """``/pjsk`` — show available commands."""
        yield event.plain_result(
            "PJSK 插件命令：\n"
            "/pjsk bind <游戏ID> — 绑定 PJSK 游戏 ID\n"
            "/pjsk help — 查看帮助"
        )

    @filter.command("pjsk bind")  # type: ignore
    async def pjsk_bind(self, event: Any) -> None:  # type: ignore
        """``/pjsk bind <game_id>`` — bind PJSK game ID to your QQ."""
        text = (event.message_str or "").strip()
        parts = text.split(maxsplit=3) if text else []
        game_id = parts[2] if len(parts) >= 3 else ""
        if not game_id or not game_id.isdigit() or not (6 <= len(game_id) <= 16):
            yield event.plain_result("游戏 ID 应为 6-16 位数字，例如：/pjsk bind 123456789")
            return
        mapper = EventMapper()
        if mapper.is_qq_official(event):
            yield event.plain_result("QQ 官方 Bot 暂不支持此功能，请使用 OneBot/NapCat 入口")
            return
        if self._runtime is None:
            yield event.plain_result("插件尚未初始化")
            return
        qq = mapper.extract_qq(event)
        user = await self._runtime.user_repo.get_by_qq(qq)
        if user is not None:
            yield event.plain_result(f"QQ {qq.value} 已绑定游戏 ID：{user.game_id or '未设置'}。重新绑定功能即将上线。")
        else:
            await self._runtime.user_repo.create(qq, game_id=game_id)
            yield event.plain_result(f"已绑定：QQ {qq.value} → 游戏 ID {game_id}")

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
                text = event.message_str or ""
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
        group_chat = _is_group_chat(event)
        bot_id = _get_self_id(event) if group_chat else ""
        has_at_bot = _is_at_bot(event, bot_id) if group_chat else False

        if img_count > 0:
            if group_chat:
                # ── Group chat: @Bot state machine ──────────────────────
                if has_at_bot and img_count == 1:
                    # @Bot + Image in same message → OCR immediately
                    pass  # fall through to OCR below
                elif has_at_bot and img_count > 1:
                    yield event.plain_result("目前一次只能识别一张")
                    event.stop_event()
                    return
                elif not has_at_bot:
                    # Plain group image — buffer for potential future @Bot
                    try:
                        image_bytes = _read_single_image_bytes(event)
                        if image_bytes is not None:
                            sender_qq = mapper.extract_qq(event)
                            gid = event.get_group_id() or ""
                            rt.image_buffer.put(
                                event.get_platform_id(), gid,
                                sender_qq, image_bytes,
                            )
                    except Exception:
                        pass  # Buffer is best-effort
                    return  # No reply — wait for @Bot
                # else: has_at_bot + no image → handled below
            # Private chat: image → OCR immediately (fall through)

        if img_count == 0 and group_chat and has_at_bot:
            # @Bot without image — check buffer for recent images
            sender_qq = mapper.extract_qq(event)
            gid = event.get_group_id() or ""
            buffered = rt.image_buffer.consume(
                event.get_platform_id(), gid, sender_qq,
                within_seconds=15.0,
            )
            if buffered is not None:
                # Found a recent image — run OCR inline
                img_count = 1  # Treat as single-image for OCR path below
                # Build a synthetic image context for OCR
                code = await _handle_buffered_image(
                    event, rt, buffered,
                )
                if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                    reply_text = await _get_image_result_text(event, code, rt, mapper)
                    yield event.plain_result(reply_text)
                    event.stop_event()
                    return
            # No buffered image → passthrough to personality

        if img_count > 0:
            if group_chat and not has_at_bot and img_count == 0:
                return  # Already handled above

            code = await _handle_image(event, rt)

            if code == PluginErrorCode.NOT_PJSK_SCREENSHOT:
                return  # Passthrough — not a PJSK screenshot

            if code == PluginErrorCode.QQ_OFFICIAL_NEEDS_BIND:
                yield event.plain_result(
                    "请先用 /pjsk bind <QQ号> 绑定 QQ 号后再使用"
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
