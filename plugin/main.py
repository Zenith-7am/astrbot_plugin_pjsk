"""PjskPlugin -- AstrBot Star plugin with OCR recognition and candidate confirmation.

Testable helper functions are at module level:
* ``_image_count(event)`` — count Image components in the event message.
* ``_handle_image(event, rt)`` — OCR recognition flow for incoming images.
* ``_handle_selection(text, user_id, conversation_id, rt)`` — candidate confirmation.
* ``_is_at_bot(event, bot_self_id)`` — check if the event message @mentions the bot.
* ``_is_group_chat(event)`` — check if the event is from a group chat.
* ``_get_self_id(event)`` — extract the bot's own ID from the event.
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
        def command_group(name: str) -> Any:  # noqa: ARG004
            """Mock command_group — returns a decorator that yields a group."""
            class _FakeGroup:
                def command(self, name: str) -> Any:  # noqa: ARG004
                    return lambda fn: fn
            def _decorator(fn: Any) -> _FakeGroup:
                return _FakeGroup()
            return _decorator

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


def _is_at_bot(event: Any, bot_self_id: str) -> bool:
    """Check if the event message @mentions the bot specifically.

    Only matches At components whose ``qq`` or ``target`` attribute
    equals the bot's self_id.  Returns ``False`` when ``bot_self_id``
    is empty (cannot determine bot identity).
    """
    if not bot_self_id:
        return False
    for c in event.message_obj.message:
        if c.__class__.__name__ != "At":
            continue
        target = getattr(c, "target", "") or getattr(c, "qq", "")
        if str(target) == str(bot_self_id):
            return True
    return False


def _is_group_chat(event: Any) -> bool:
    """Check if the event is from a group chat (not private)."""
    return event.get_group_id() is not None


def _get_self_id(event: Any) -> str:
    """Get the bot's own ID from the event.

    Prefer ``event.message_obj.self_id`` (AstrBot v3), then
    ``event.get_self_id()``.
    """
    try:
        sid = event.message_obj.self_id
        if sid is not None:
            return str(sid)
    except (AttributeError, TypeError):
        pass
    try:
        sid = event.get_self_id()
        if sid is not None:
            return str(sid)
    except (AttributeError, TypeError):
        pass
    return ""


async def _handle_image(event: Any, rt: PluginRuntime) -> PluginErrorCode:
    """Process incoming image for OCR score recognition.

    Flow
    ----
    1. Count images — reject 0 or >1 immediately.
    2. Extract image context via ``EventMapper.extract_async()``.
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
    ctx = await mapper.extract_async(event, rt.http_client)
    if ctx is None:
        return PluginErrorCode.NOT_PJSK_SCREENSHOT

    # QQ Official Bot already bypassed in on_message — qq_number must be set
    if ctx.qq_number is None:
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
            rt.set_pending(
                user.id.value, ctx.platform_id, conv_id, cid, display_text,
            )
        return PluginErrorCode.CANDIDATES_AVAILABLE

    return PluginErrorCode.NOT_PJSK_SCREENSHOT


async def _handle_selection(
    text: str,
    user_id: UserId,
    platform_id: str,
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

    cid = rt.get_pending_candidate_set_id(
        user_id.value, platform_id, conversation_id,
    )
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

    # Clear on expired/not_found — the candidate is gone
    from pjsk_core.application.confirm_candidate import ConfirmError
    if result.error in (ConfirmError.EXPIRED, ConfirmError.NOT_FOUND):
        rt.clear_pending(user_id.value, platform_id, conversation_id)
        return True, f"确认失败：{result.error.value}"
    if result.error is not None:
        return True, f"确认失败：{result.error.value}"

    # Success — clean up pending
    rt.clear_pending(user_id.value, platform_id, conversation_id)
    return True, None


async def _read_single_image_bytes_async(
    event: Any, http_client: Any,
) -> bytes | None:
    """Read the first image from an event as raw bytes (async path)."""
    for c in event.message_obj.message:
        if c.__class__.__name__ == "Image":
            return await EventMapper._read_image_bytes_async(c, http_client)
    return None


async def _handle_buffered_image(
    event: Any, rt: PluginRuntime, image_bytes: bytes,
) -> PluginErrorCode:
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
    gateway = EventMapper._gateway_name(event.get_platform_id())
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
            rt.set_pending(
                user.id.value, event.get_platform_id(), conv_id, cid, display_text,
            )
        return PluginErrorCode.CANDIDATES_AVAILABLE
    return PluginErrorCode.NOT_PJSK_SCREENSHOT


async def _get_image_result_text(
    event: Any, code: PluginErrorCode, rt: PluginRuntime, mapper: EventMapper,
) -> str:
    """Get the appropriate reply text for an image recognition result."""
    if code == PluginErrorCode.CANDIDATES_AVAILABLE:
        qq = mapper.extract_qq(event)
        user = await rt.user_repo.get_by_qq(qq)
        if user is not None:
            platform_id = event.get_platform_id()
            conv_id = mapper.extract_conversation_id(event)
            display = rt.get_pending_display_text(
                user.id.value, platform_id, conv_id,
            )
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

    # ── Commands ─────────────────────────────────────────────────────────

    @filter.command_group("pjsk")  # type: ignore
    def pjsk_command_group(self) -> None:
        """``/pjsk`` command group — sub-commands registered below."""
        pass

    @pjsk_command_group.command("bind")  # type: ignore
    async def pjsk_bind(self, event: Any, game_id: str = "") -> None:  # type: ignore
        """``/pjsk bind <game_id>`` — bind PJSK game ID to your QQ."""
        # QQ Official early gate
        mapper = EventMapper()
        if mapper.is_qq_official(event):
            yield event.plain_result("QQ 官方入口暂未开放，请暂时使用 OneBot/NapCat")
            return

        game_id = (game_id or "").strip()
        if not game_id or not game_id.isdigit() or not (6 <= len(game_id) <= 16):
            yield event.plain_result("游戏 ID 应为 6-16 位数字，例如：/pjsk bind 1234567890123456")
            return

        if self._runtime is None:
            yield event.plain_result("插件尚未初始化")
            return

        qq = mapper.extract_qq(event)
        rt = self._runtime
        user = await rt.user_repo.get_by_qq(qq)

        if user is None:
            # First-time user: create with game_id
            user = await rt.user_repo.create(qq, game_id=game_id)
            yield event.plain_result(f"已绑定：QQ {qq.value} → 游戏 ID {game_id}")
            return

        if user.game_id == game_id:
            # Idempotent: same game_id already bound
            yield event.plain_result(f"QQ {qq.value} 已绑定游戏 ID：{game_id}")
            return

        if user.game_id is not None and user.game_id != game_id:
            # Rebinding to a different game_id — reject for now
            yield event.plain_result(
                f"QQ {qq.value} 已绑定游戏 ID：{user.game_id}。"
                f"更换绑定暂不支持，请联系管理员。"
            )
            return

        # user.game_id is None → auto-registered, update
        user = await rt.user_repo.bind_game_id(user.id, game_id)  # type: ignore[attr-defined]
        yield event.plain_result(f"已绑定：QQ {qq.value} → 游戏 ID {game_id}")

    # ── Main message handler ──────────────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)  # type: ignore
    async def on_message(self, event: Any) -> None:  # type: ignore
        """Handle incoming messages — candidate selection, image recognition.

        Processing order (group chat uses a deterministic state machine):
        1.  QQ Official early bypass
        2.  Candidate selection (non-image text)
        3.  Private chat: single-image OCR / multi-image reject
        4.  Group: @Bot+Image same message → OCR
        5.  Group: @Bot only → consume buffer or arm wait
        6.  Group: image only → consume arm or cache
        7.  Everything else → passthrough to AstrBot personality
        """
        if self._runtime is None:
            return

        rt = self._runtime
        mapper = EventMapper()

        # ── 0. QQ Official early bypass ───────────────────────────────
        if mapper.is_qq_official(event):
            if _image_count(event) > 0:
                yield event.plain_result(
                    "QQ 官方入口暂未开放，请暂时使用 OneBot/NapCat"
                )
                event.stop_event()
            return  # Text → passthrough (no QqNumber constructed)

        # ── 1. /pjsk commands routed by framework — skip ──────────────

        # ── 2. Candidate selection (non-image messages) ───────────────
        img_count = _image_count(event)
        if img_count == 0:
            try:
                text = event.message_str or ""
            except (AttributeError, TypeError):
                text = ""
            if text.strip():
                qq = mapper.extract_qq(event)
                user = await rt.user_repo.get_by_qq(qq)
                if user is not None:
                    platform_id = event.get_platform_id()
                    conv_id = mapper.extract_conversation_id(event)
                    cid = rt.get_pending_candidate_set_id(
                        user.id.value, platform_id, conv_id,
                    )
                    if cid is not None:
                        is_selection, err_msg = await _handle_selection(
                            text, user.id, platform_id, conv_id, rt,
                        )
                        if is_selection:
                            if err_msg is not None:
                                yield event.plain_result(err_msg)
                            else:
                                yield event.plain_result("已确认成绩")
                            event.stop_event()
                            return
                    # Not a selection, but had candidates → clear stale pointer
                    # (expired/not-found/consumed candidates shouldn't block chat)
                    # Only reached if _handle_selection didn't match
            return  # Passthrough to AstrBot personality

        # ── 3. Private chat image handling ────────────────────────────
        group_chat = _is_group_chat(event)

        if not group_chat:
            if img_count > 1:
                yield event.plain_result("目前一次只能识别一张")
                event.stop_event()
                return
            code = await _handle_image(event, rt)
            if code == PluginErrorCode.NOT_PJSK_SCREENSHOT:
                return  # Passthrough
            reply_text = await _get_image_result_text(event, code, rt, mapper)
            yield event.plain_result(reply_text)
            event.stop_event()
            return

        # ── 4. Group chat state machine ───────────────────────────────
        bot_id = _get_self_id(event)
        has_at = _is_at_bot(event, bot_id)
        platform_id = event.get_platform_id()
        group_id = event.get_group_id() or ""
        sender_qq = mapper.extract_qq(event)

        # 4a. @Bot + Image same message → OCR immediately
        if has_at and img_count == 1:
            code = await _handle_image(event, rt)
            if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                reply_text = await _get_image_result_text(event, code, rt, mapper)
                yield event.plain_result(reply_text)
                event.stop_event()
            return

        # 4b. @Bot + multiple images → reject
        if has_at and img_count > 1:
            yield event.plain_result("目前一次只能识别一张")
            event.stop_event()
            return

        # 4c. @Bot without image → consume buffer or arm
        if has_at and img_count == 0:
            buffered = rt.image_buffer.consume(
                platform_id, group_id, sender_qq, within_seconds=15.0,
            )
            if buffered is not None:
                code = await _handle_buffered_image(event, rt, buffered)
                if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                    reply_text = await _get_image_result_text(
                        event, code, rt, mapper,
                    )
                    yield event.plain_result(reply_text)
                    event.stop_event()
                return
            # No buffered image — arm and passthrough
            rt.image_buffer.arm(platform_id, group_id, sender_qq)
            return

        # 4d. No @Bot — check arm or cache
        if not has_at:
            if img_count == 1:
                armed = rt.image_buffer.consume_arm(
                    platform_id, group_id, sender_qq, within_seconds=15.0,
                )
                if armed:
                    code = await _handle_image(event, rt)
                    if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                        reply_text = await _get_image_result_text(
                            event, code, rt, mapper,
                        )
                        yield event.plain_result(reply_text)
                        event.stop_event()
                    return
                # Cache image for potential future @Bot
                try:
                    image_bytes = await _read_single_image_bytes_async(
                        event, rt.http_client,
                    )
                    if image_bytes is not None:
                        rt.image_buffer.put(
                            platform_id, group_id, sender_qq, image_bytes,
                        )
                except Exception:
                    pass  # Buffer is best-effort
            # Multi-image without @Bot → silently ignore
            return

        # ── 5. Passthrough ───────────────────────────────────────────
        return

    async def terminate(self) -> None:
        """Clean up plugin resources."""
        if self._runtime:
            await self._runtime.close()
            self._runtime = None
