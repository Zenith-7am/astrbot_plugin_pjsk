"""Stateless helper functions for PjskPlugin message handling.

These are extracted from the original ``pjsk_emubot.main`` module so
that the plugin class can live in the plugin-root ``main.py`` (as
required by AstrBot v4.26.5's handler-discovery mechanism) while the
helper logic remains testable in isolation.

All parameters that represent AstrBot types use ``Any`` to avoid a
hard dependency on the ``astrbot`` package — callers inside the
AstrBot process pass real AstrBot events; tests pass fakes.
"""
from __future__ import annotations

import re
from typing import Any

from pjsk_emubot.candidate_presenter import CandidatePresenter
from pjsk_emubot.event_mapper import EventMapper
from pjsk_emubot.reply_builder import PluginErrorCode, ReplyBuilder
from pjsk_emubot.runtime import PluginRuntime
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import CandidateSet as _CandidateSet


# ── Helpers ───────────────────────────────────────────────────────────────────


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


def _text_beyond_components(event: Any) -> str:
    """Return message text after stripping Image and At components.

    An empty string means the message is effectively "empty" from the
    plugin's perspective (e.g. a bare @Bot mention with no text).
    """
    try:
        raw = event.message_str or ""
    except (AttributeError, TypeError):
        raw = ""
    try:
        components = list(event.message_obj.message)
    except (AttributeError, TypeError):
        components = []
    non_structural = [
        c for c in components
        if c.__class__.__name__ not in ("Image", "At")
    ]
    if non_structural:
        return raw.strip()
    return ""


def _is_at_bot(event: Any, bot_self_id: str) -> bool:
    """Check if the event message @mentions the bot specifically."""
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
    """Get the bot's own ID from the event."""
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


async def _handle_image(
    event: Any, rt: PluginRuntime,
) -> tuple[PluginErrorCode, Any | None]:
    """Process incoming image for OCR score recognition.

    Returns ``(code, recognize_result)``.  *recognize_result* is the
    full :class:`~pjsk_core.application.recognize_score.RecognizeResult`
    on SUCCESS, ``None`` otherwise.  Callers use the result to build a
    rich echo via :func:`~pjsk_emubot.result_dto.build_score_echo`.
    """
    count = _image_count(event)
    if count == 0:
        return PluginErrorCode.NOT_PJSK_SCREENSHOT, None
    if count > 1:
        return PluginErrorCode.MULTIPLE_IMAGES, None

    mapper = EventMapper()
    ctx = await mapper.extract_async(event, rt.http_client)
    if ctx is None:
        return PluginErrorCode.NOT_PJSK_SCREENSHOT, None

    if ctx.qq_number is None:
        return PluginErrorCode.QQ_OFFICIAL_NEEDS_BIND, None

    user = await rt.user_repo.get_or_create(ctx.qq_number)

    if not rt.rate_limiter.check(user.id):
        return PluginErrorCode.USER_RATE_LIMITED, None
    rt.rate_limiter.mark(user.id)

    if rt.recognize_score is None:
        return PluginErrorCode.ALL_ENGINES_DOWN, None

    result = await rt.recognize_score.recognize(
        user.id, ctx.image_bytes, source_gateway=ctx.source_gateway,
    )

    if result.score_attempt is not None:
        return PluginErrorCode.SUCCESS, result

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
        return PluginErrorCode.CANDIDATES_AVAILABLE, result

    return PluginErrorCode.NOT_PJSK_SCREENSHOT, None


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
    - ``(True, "...")`` — selection detected but failed
    """
    text = text.strip()

    cid = rt.get_pending_candidate_set_id(
        user_id.value, platform_id, conversation_id,
    )
    if cid is None:
        return False, None

    selection: int | None = None

    m = re.match(r'选\s+(\S+)\s+(\d+)', text)
    if m:
        matched_cid, num = m.group(1), int(m.group(2))
        if matched_cid == cid:
            selection = num

    if selection is None:
        try:
            selection = int(text)
        except ValueError:
            return False, None

    result = await rt.confirm_candidate.confirm(
        user_id, cid, selection,
    )

    from pjsk_core.application.confirm_candidate import ConfirmError
    if result.error in (ConfirmError.EXPIRED, ConfirmError.NOT_FOUND):
        rt.clear_pending(user_id.value, platform_id, conversation_id)
        return True, f"确认失败：{result.error.value}"
    if result.error is not None:
        return True, f"确认失败：{result.error.value}"

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
) -> tuple[PluginErrorCode, Any | None]:
    """Run OCR on buffered image bytes (from EphemeralImageBuffer)."""
    mapper = EventMapper()
    if mapper.is_qq_official(event):
        return PluginErrorCode.QQ_OFFICIAL_NEEDS_BIND, None
    qq = mapper.extract_qq(event)
    user = await rt.user_repo.get_or_create(qq)
    if not rt.rate_limiter.check(user.id):
        return PluginErrorCode.USER_RATE_LIMITED, None
    rt.rate_limiter.mark(user.id)
    if rt.recognize_score is None:
        return PluginErrorCode.ALL_ENGINES_DOWN, None
    gateway = EventMapper._gateway_name(event.get_platform_id())
    result = await rt.recognize_score.recognize(
        user.id, image_bytes, source_gateway=gateway,
    )
    if result.score_attempt is not None:
        return PluginErrorCode.SUCCESS, result
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
        return PluginErrorCode.CANDIDATES_AVAILABLE, result
    return PluginErrorCode.NOT_PJSK_SCREENSHOT, None


async def _get_image_result_text(
    event: Any,
    code: PluginErrorCode,
    rt: PluginRuntime,
    mapper: EventMapper,
    result: Any | None = None,  # RecognizeResult from application layer
) -> str:
    """Get the appropriate reply text for an image recognition result.

    On SUCCESS, builds a rich echo from *result* (song, difficulty,
    status, accuracy, rating, decision source).  Falls back to "已记录"
    if the result does not contain enough information.
    """
    if code == PluginErrorCode.SUCCESS and result is not None:
        from pjsk_emubot.result_dto import build_score_echo, format_score_echo

        echo = build_score_echo(result)
        if echo is not None:
            return format_score_echo(echo)
        return ReplyBuilder.error_text(code)

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
