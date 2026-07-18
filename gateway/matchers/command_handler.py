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
    """Group: .emu/. prefix, OR @Bot + known bare command (注册/register/b20/etc.)."""
    if event.message_type != "group":
        return False
    text = event.get_plaintext().strip()
    # .emu / 。emu prefix always triggers
    if _EMU_PREFIX.match(text):
        return True
    # @Bot with a known bare command — strip leading @xxx mentions
    if event.is_tome():
        # Remove @Bot mention(s) from the text and try bare parsing
        cleaned = text
        for seg in event.message:
            if seg.type == "at" and seg.data.get("qq") == str(event.self_id):
                cleaned = cleaned.replace(
                    f"[CQ:at,qq={event.self_id}]", "", 1,
                )
        cleaned = cleaned.strip()
        if cleaned:
            return parse_trigger(cleaned, is_group=False) is not None
    return False


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
        # Try render image card → fall back to text
        png: bytes | None = None
        if (result.validated is not None
                and result.validated.primary is not None
                and runtime.renderer is not None
                and result.score_attempt is not None):
            try:
                from pjsk_core.application.render_ocr_card import render_ocr_card

                v = result.validated
                obs = v.observation
                chart = v.primary.chart
                attempt = result.score_attempt

                jacket_url: str | None = None
                if runtime.jacket_cache is not None and chart is not None:
                    jacket_url = await runtime.jacket_cache.get_jacket(
                        chart.song_id,
                    )

                png = await render_ocr_card(
                    song_id=chart.song_id if chart else 0,
                    title_ja=obs.song_title or "",
                    title_cn="",
                    difficulty=obs.difficulty.value,
                    level=chart.official_level if chart else obs.displayed_level,
                    constant=chart.community_constant if chart else "",
                    accuracy=attempt.accuracy,
                    rating=attempt.rating,
                    sp="—",
                    perfect=obs.judgements.perfect,
                    great=obs.judgements.great,
                    good=obs.judgements.good,
                    bad=obs.judgements.bad,
                    miss=obs.judgements.miss,
                    status=attempt.status.value,
                    qq_id=msg.external_user_id,
                    jacket_data_url=jacket_url,
                    renderer=runtime.renderer,
                )
            except Exception:
                _logger.exception("OCR card render failed, falling back to text")

        if png is not None:
            from gateway.adapters.reply_sender import send_image_reply
            from pjsk_core.application.replies import ImageReply
            await send_image_reply(
                bot, event,
                ImageReply(image_bytes=png, mime_type="image/png"),
            )
        else:
            if readonly:
                text = (
                    _format_readonly_result(result)
                    if result.validated is not None
                    else "识别完成但无法解析结果"
                )
            else:
                text = _format_consensus_reply(result, None)
            await send_text_reply(bot, event, TextReply(text=text))
    elif decision == VisionRaceDecision.DISAGREEMENT:
        if readonly:
            text = _format_candidates_text(result)
        else:
            from gateway.matchers.image_handler import _handle_disagreement
            text = await _handle_disagreement(result, user, msg, runtime)
        await send_text_reply(bot, event, TextReply(text=text))
    elif decision == VisionRaceDecision.ALL_FAILED:
        await send_text_reply(
            bot, event,
            TextReply(text="所有识别模型均失败，请稍后重试"),
        )
    else:
        await send_text_reply(
            bot, event, TextReply(text="识别失败，请稍后重试"),
        )


# ── B20 / Difficulty ranking ─────────────────────────────────────────────────


async def _handle_b20(
    bot: Bot, event: MessageEvent, msg: IncomingMessage,
) -> None:
    """Return B20 ranking (rendered image, fallback text)."""
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
        b20_result = await runtime.query_b20.query(user.id)
    except Exception:
        _logger.exception("B20 query failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not b20_result.entries:
        await send_text_reply(bot, event, TextReply(text="暂无 B20 成绩记录"))
        return

    # Try render image → fall back to text
    png: bytes | None = None
    if runtime.renderer is not None:
        try:
            from pjsk_core.application.render_b20 import render_b20
            _logger.info(
                "B20 render attempt: renderer_present=true entry_count=%d jacket_cache_present=%s",
                len(b20_result.entries),
                runtime.jacket_cache is not None,
            )
            png = await render_b20(
                b20_result,
                renderer=runtime.renderer,
                jacket_cache=runtime.jacket_cache,
            )
            _logger.info(
                "B20 render result=%s png_bytes=%d",
                "png" if png is not None else "none",
                len(png) if png is not None else 0,
            )
        except Exception:
            _logger.exception("B20 render failed, falling back to text")

    if png is not None:
        from gateway.adapters.reply_sender import send_image_reply
        from pjsk_core.application.replies import ImageReply
        await send_image_reply(
            bot, event,
            ImageReply(image_bytes=png, mime_type="image/png"),
        )
    else:
        lines = ["B20 排行", ""]
        for i, e in enumerate(b20_result.entries[:20], 1):
            lines.append(
                f"[{i}] {e.song_title} · MA {e.official_level} · "
                f"ACC {e.accuracy:.2f}% · Rating {e.rating:.2f}"
            )
        lines.append("")
        lines.append(f"B20 平均: {b20_result.b20_avg:.2f}")
        if b20_result.sp > 0:
            lines.append(f"SEKAI POWER: {b20_result.sp:.2f}")
        await send_text_reply(bot, event, TextReply(text="\n".join(lines)))


async def _handle_my_difficulty(
    bot: Bot, event: MessageEvent, msg: IncomingMessage, level: int | None,
) -> None:
    """Return personal difficulty ranking."""
    if _runtime is None or level is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用"))
        return

    from pjsk_core.domain.charts import Difficulty
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
        ranking = await runtime.query_difficulty_ranking.query_personal(
            user.id, Difficulty.MASTER, level,
        )
    except Exception:
        _logger.exception("Personal difficulty ranking failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not ranking.entries:
        await send_text_reply(bot, event, TextReply(text=f"MA {level} 暂无成绩"))
        return

    # Try render image → fall back to text
    png: bytes | None = None
    if runtime.renderer is not None:
        try:
            from pjsk_core.application.render_difficulty_ranking import (
                render_difficulty_ranking,
            )
            png = await render_difficulty_ranking(
                ranking,
                renderer=runtime.renderer,
                jacket_cache=runtime.jacket_cache,
            )
        except Exception:
            _logger.exception("Difficulty ranking render failed, falling back to text")

    if png is not None:
        from gateway.adapters.reply_sender import send_image_reply
        from pjsk_core.application.replies import ImageReply
        await send_image_reply(
            bot, event,
            ImageReply(image_bytes=png, mime_type="image/png"),
        )
    else:
        lines = [f"个人 MA {level} 排行", ""]
        for i, e in enumerate(ranking.entries[:20], 1):
            status_str = e.status.value.upper() if e.status else "未游玩"
            acc_str = f"ACC {e.accuracy:.2f}%" if e.accuracy is not None else ""
            rating_str = f"Rating {e.rating:.2f}" if e.rating is not None else ""
            parts = [f"[{i}] {e.song_title}", status_str, acc_str, rating_str]
            lines.append(" · ".join(p for p in parts if p))
        await send_text_reply(bot, event, TextReply(text="\n".join(lines)))


async def _handle_global_difficulty(
    bot: Bot, event: MessageEvent, msg: IncomingMessage, level: int | None,
) -> None:
    """Return global difficulty ranking."""
    if _runtime is None or level is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用"))
        return

    from pjsk_core.domain.charts import Difficulty
    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    try:
        ranking = await runtime.query_difficulty_ranking.query_global(
            Difficulty.MASTER, level,
        )
    except Exception:
        _logger.exception("Global difficulty ranking failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not ranking.entries:
        await send_text_reply(bot, event, TextReply(text=f"MA {level} 暂无排行数据"))
        return

    # Try render image → fall back to text
    png: bytes | None = None
    if runtime.renderer is not None:
        try:
            from pjsk_core.application.render_difficulty_ranking import (
                render_difficulty_ranking,
            )
            png = await render_difficulty_ranking(
                ranking,
                renderer=runtime.renderer,
                jacket_cache=runtime.jacket_cache,
            )
        except Exception:
            _logger.exception("Global difficulty ranking render failed, falling back to text")

    if png is not None:
        from gateway.adapters.reply_sender import send_image_reply
        from pjsk_core.application.replies import ImageReply
        await send_image_reply(
            bot, event,
            ImageReply(image_bytes=png, mime_type="image/png"),
        )
    else:
        lines = [f"MA {level} 全局排行（定数降序）", ""]
        for i, e in enumerate(ranking.entries[:20], 1):
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
