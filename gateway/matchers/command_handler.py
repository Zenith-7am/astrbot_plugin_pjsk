"""NoneBot matcher for commands — .emu prefix (group) / bare commands (private)."""
from __future__ import annotations

import logging
import re

import nonebot
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.rule import Rule

from pjsk_core.application.replies import TextReply
from pjsk_core.domain.users import QqNumber
from gateway.commands import (
    EmuCommand,
    ParsedTrigger,
    build_help_text,
    build_status_text,
    parse_trigger,
    qq_allowed,
)
from gateway.adapters.event_mapper import IncomingMessage, map_event
from gateway.adapters.reply_sender import send_text_reply
from gateway.matchers.image_handler import get_pending_store

_logger = logging.getLogger(__name__)

# Injected by bootstrap after Runtime assembly.
_runtime: object | None = None


def set_runtime_for_commands(runtime: object) -> None:
    """Register the Runtime so matchers can call use cases."""
    global _runtime
    _runtime = runtime


# ── Trigger rules ────────────────────────────────────────────────────────────

_EMU_PREFIX = re.compile(r"^[.。]emu(?:\s|$)")
_LEGACY_EMU = re.compile(r"^/emu\b")
_CANDIDATE_ONLY = re.compile(r"^\d{1,2}$")


async def _group_emu_trigger(event: MessageEvent) -> bool:
    """Group: only messages starting with .emu or .emu trigger."""
    if event.message_type != "group":
        return False
    text = event.get_plaintext().strip()
    return bool(_EMU_PREFIX.match(text))


async def _private_cmd_trigger(event: MessageEvent) -> bool:
    """Private: bare commands (b20, 我的maXX, etc.) — no prefix needed.
    Excludes plain images (handled by image_handler) and pure numbers
    (handled by candidate_handler).
    """
    if event.message_type != "private":
        return False
    # Don't capture messages with images (image_handler handles those)
    if any(seg.type == "image" for seg in event.message):
        return False
    text = event.get_plaintext().strip()
    if not text:
        return False
    # Don't capture pure numbers (candidate_handler)
    if _CANDIDATE_ONLY.match(text):
        return False
    # Don't capture plain chat
    return parse_trigger(text, is_group=False) is not None


group_emu = on_message(rule=Rule(_group_emu_trigger), priority=5, block=False)
private_cmd = on_message(rule=Rule(_private_cmd_trigger), priority=5, block=False)


# ── Handlers ─────────────────────────────────────────────────────────────────


@group_emu.handle()
async def _handle_group_emu(bot: Bot, event: MessageEvent) -> None:
    """Handle .emu command in group chat."""
    msg = map_event(event)
    if not qq_allowed(msg.external_user_id):
        return

    text = event.get_plaintext().strip()
    parsed = parse_trigger(text, is_group=True)
    if parsed is None:
        return

    await _dispatch(bot, event, msg, parsed)


@private_cmd.handle()
async def _handle_private_cmd(bot: Bot, event: MessageEvent) -> None:
    """Handle bare commands in private chat."""
    msg = map_event(event)
    if not qq_allowed(msg.external_user_id):
        return

    text = event.get_plaintext().strip()
    parsed = parse_trigger(text, is_group=False)
    if parsed is None:
        return

    await _dispatch(bot, event, msg, parsed)


async def _dispatch(
    bot: Bot, event: MessageEvent, msg: IncomingMessage, parsed: ParsedTrigger,
) -> None:
    """Route a parsed command to the appropriate handler."""
    cmd = parsed.command

    _logger.info(
        "command=%s conversation_type=%s level=%s",
        cmd.value, msg.conversation_type.value, parsed.level,
    )

    if cmd == EmuCommand.OCR_TRIGGER:
        await _handle_ocr_trigger(bot, event, msg)
    elif cmd == EmuCommand.B20:
        await _handle_b20(bot, event, msg)
    elif cmd == EmuCommand.MY_DIFFICULTY:
        await _handle_my_difficulty(bot, event, msg, parsed.level)
    elif cmd == EmuCommand.GLOBAL_DIFFICULTY:
        await _handle_global_difficulty(bot, event, msg, parsed.level)
    elif cmd == EmuCommand.REGISTER:
        await _handle_register(bot, event, msg)
    elif cmd == EmuCommand.HELP:
        await send_text_reply(bot, event, TextReply(text=build_help_text()))
    elif cmd == EmuCommand.STATUS:
        await send_text_reply(
            bot, event,
            TextReply(text=build_status_text(len(nonebot.get_bots()))),
        )
    else:
        await send_text_reply(
            bot, event,
            TextReply(text="未知命令，请使用 /emu help 查看可用命令"),
        )


# ── OCR trigger (group: .emu with no args) ───────────────────────────────────


async def _handle_ocr_trigger(
    bot: Bot, event: MessageEvent, msg: IncomingMessage,
) -> None:
    """Pop the user's latest image from PendingImageStore and run OCR."""
    store = get_pending_store()
    group_id = str(getattr(event, "group_id", "0"))
    qq = msg.external_user_id

    image_data = store.pop(group_id, qq)
    if image_data is None:
        await send_text_reply(
            bot, event,
            TextReply(text="未找到30秒内的截图，请先发图再 .emu"),
        )
        return

    if _runtime is None:
        await send_text_reply(bot, event, TextReply(text="服务正在启动中，请稍后再试"))
        return

    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]
    from gateway.matchers.image_handler import _validate_image

    error = _validate_image(image_data)
    if error is not None:
        await send_text_reply(bot, event, TextReply(text=error))
        return

    # Resolve user
    qq_obj = QqNumber(qq)
    user = None
    try:
        user = await runtime.user_repo.get_by_qq(qq_obj)
    except Exception:
        _logger.exception("User lookup failed in OCR trigger")
        await send_text_reply(bot, event, TextReply(text="服务异常，请稍后重试"))
        return

    if user is None:
        await send_text_reply(bot, event, TextReply(text="请先使用 .emu register 注册"))
        return

    if runtime.recognize_score is None or runtime.http_client is None:
        await send_text_reply(bot, event, TextReply(text="识别服务暂不可用"))
        return

    import os
    readonly = os.environ.get("PJSK_OCR_READONLY") == "1"
    _logger.info(
        "pending OCR: group=%s qq=%s size=%d readonly=%s",
        group_id, qq, len(image_data), readonly,
    )

    try:
        result = await runtime.recognize_score.recognize(
            user.id, image_data, source_gateway="onebot", readonly=readonly,
        )
    except Exception:
        _logger.exception("OCR failed in .emu trigger")
        await send_text_reply(bot, event, TextReply(text="识别失败，请稍后重试"))
        return

    # Format result (reuse image_handler formatting for now)
    from gateway.matchers.image_handler import (
        _format_candidates_text,
        _format_consensus_reply,
        _format_readonly_result,
        _log_engine_results,
    )
    from pjsk_core.application.vision_race import VisionRaceDecision

    _log_engine_results(result)
    decision = result.outcome.decision

    if decision in (VisionRaceDecision.CONSENSUS, VisionRaceDecision.DEGRADED_SINGLE):
        if readonly:
            text = _format_readonly_result(result) if result.validated is not None else "识别完成但无法解析结果"
        else:
            text = _format_consensus_reply(result, None)
    elif decision == VisionRaceDecision.DISAGREEMENT:
        if readonly:
            text = _format_candidates_text(result)
        else:
            from gateway.matchers.image_handler import _handle_disagreement
            text = await _handle_disagreement(result, user, msg, runtime)
    elif decision == VisionRaceDecision.ALL_FAILED:
        text = "所有识别模型均失败，请稍后重试"
    else:
        text = "识别失败，请稍后重试"

    await send_text_reply(bot, event, TextReply(text=text))


# ── B20 / Difficulty ranking — text replies for now (image rendering is follow-up) ─


async def _handle_b20(
    bot: Bot, event: MessageEvent, msg: IncomingMessage,
) -> None:
    """Return B20 ranking."""
    if _runtime is None:
        await send_text_reply(bot, event, TextReply(text="服务正在启动中，请稍后再试"))
        return

    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    qq = QqNumber(msg.external_user_id)
    try:
        user = await runtime.user_repo.get_by_qq(qq)
    except Exception:
        _logger.exception("User lookup in b20")
        await send_text_reply(bot, event, TextReply(text="服务异常"))
        return

    if user is None:
        await send_text_reply(bot, event, TextReply(text="请先使用 .emu register 注册"))
        return

    try:
        b20_result = await runtime.query_b20.execute(user.id)
    except Exception:
        _logger.exception("B20 query failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not b20_result.entries:
        await send_text_reply(bot, event, TextReply(text="暂无 B20 成绩记录"))
        return

    lines = ["B20 排行", ""]
    for i, e in enumerate(b20_result.entries[:20], 1):
        lines.append(
            f"[{i}] {e.song_title} · MA {e.official_level} · "
            f"ACC {e.accuracy:.2f}% · Rating {e.rating:.2f}"
        )
    lines.append("")
    lines.append(f"B20 平均: {b20_result.average:.2f}")
    if b20_result.total_sp > 0:
        lines.append(f"SEKAI POWER: {b20_result.total_sp:.2f}")

    await send_text_reply(bot, event, TextReply(text="\n".join(lines)))


async def _handle_my_difficulty(
    bot: Bot, event: MessageEvent, msg: IncomingMessage, level: int | None,
) -> None:
    """Return personal difficulty ranking."""
    if _runtime is None or level is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用"))
        return

    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    qq = QqNumber(msg.external_user_id)
    try:
        user = await runtime.user_repo.get_by_qq(qq)
    except Exception:
        _logger.exception("User lookup in my_difficulty")
        await send_text_reply(bot, event, TextReply(text="服务异常"))
        return

    if user is None:
        await send_text_reply(bot, event, TextReply(text="请先使用 .emu register 注册"))
        return

    try:
        ranking = await runtime.query_difficulty_ranking.execute_personal(
            user.id, "master", level,
        )
    except Exception:
        _logger.exception("Personal difficulty ranking failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not ranking:
        await send_text_reply(bot, event, TextReply(text=f"MA {level} 暂无成绩"))
        return

    lines = [f"个人 MA {level} 排行", ""]
    for i, e in enumerate(ranking[:20], 1):
        status = getattr(e, "status", "?")
        acc = getattr(e, "accuracy", 0.0)
        rating = getattr(e, "rating", 0.0)
        lines.append(
            f"[{i}] {e.song_title} · {status} · ACC {acc:.2f}% · Rating {rating:.2f}"
        )

    await send_text_reply(bot, event, TextReply(text="\n".join(lines)))


async def _handle_global_difficulty(
    bot: Bot, event: MessageEvent, msg: IncomingMessage, level: int | None,
) -> None:
    """Return global difficulty ranking."""
    if _runtime is None or level is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用"))
        return

    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    try:
        ranking = await runtime.query_difficulty_ranking.execute_global(
            "master", level,
        )
    except Exception:
        _logger.exception("Global difficulty ranking failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not ranking:
        await send_text_reply(bot, event, TextReply(text=f"MA {level} 暂无排行数据"))
        return

    lines = [f"MA {level} 全局排行（定数降序）", ""]
    for i, e in enumerate(ranking[:20], 1):
        lines.append(
            f"[{i}] {e.song_title} · 定数 {e.community_constant} · "
            f"MA {e.official_level}"
        )

    await send_text_reply(bot, event, TextReply(text="\n".join(lines)))


# ── Register ─────────────────────────────────────────────────────────────────


async def _handle_register(
    bot: Bot, event: MessageEvent, msg: IncomingMessage,
) -> None:
    """Handle .emu register — create a user record from QQ identity."""
    if _runtime is None:
        await send_text_reply(
            bot, event,
            TextReply(text="服务正在启动中，请稍后再试"),
        )
        return

    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    if runtime.register_user is None:
        await send_text_reply(
            bot, event,
            TextReply(text="注册功能暂未开放"),
        )
        return

    try:
        qq = QqNumber(msg.external_user_id)
        _user, is_new = await runtime.register_user.execute(qq)
        if is_new:
            await send_text_reply(bot, event, TextReply(text="注册成功"))
        else:
            await send_text_reply(
                bot, event,
                TextReply(text="注册成功（你已经注册过了哦！）"),
            )
    except Exception:
        _logger.exception("Register failed")
        await send_text_reply(
            bot, event,
            TextReply(text="注册失败，请稍后重试"),
        )
