"""NoneBot matcher for commands — .emu prefix (group) / bare commands (private)."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import nonebot
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.rule import Rule

from pjsk_core.application.replies import TextReply
from pjsk_core.domain.scores import ScoreStatus
from pjsk_core.domain.users import QqNumber

if TYPE_CHECKING:
    from pjsk_core.domain.b20 import B20Result
    from pjsk_core.domain.difficulty_ranking import DifficultyRanking
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


def _mask_id(raw: str) -> str:
    """Return a privacy-safe version of a QQ number or group ID.

    Keeps the first 2 and last 2 characters; replaces the middle with ``…``.
    Short ids (≤4 chars) are fully masked.
    """
    if len(raw) <= 4:
        return "*" * len(raw)
    return raw[:2] + "…" + raw[-2:]


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
        await _handle_my_difficulty(bot, event, msg, parsed.level, parsed.difficulty)
    elif cmd == EmuCommand.GLOBAL_DIFFICULTY:
        await _handle_global_difficulty(bot, event, msg, parsed.level, parsed.difficulty)
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
        _mask_id(group_id), _mask_id(str(qq)), len(image_data), readonly,
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
        try:
            from gateway.matchers.image_handler import _try_render_ocr_card
        except ImportError:
            _logger.exception("Cannot import _try_render_ocr_card")
            _try_render_ocr_card = None  # type: ignore[assignment]

        if _try_render_ocr_card is not None:
            png = await _try_render_ocr_card(
                result, runtime, msg, None, readonly,
            )
        else:
            png = None

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


def _build_b20_payload(
    result: "B20Result",
    jacket_map: dict[int, str],
) -> dict[str, object]:
    """Assemble the COMPLETE JS payload for b20.js.

    Every field the JS renderer reads is explicitly assigned here —
    nothing is silently dropped by an intermediate translation layer.
    """
    from pjsk_core.application.render_ocr_card import _get_acc_grade

    songs: list[dict[str, object]] = []
    for entry in result.entries:
        ap = entry.status == ScoreStatus.AP
        grade_label, grade_class = _get_acc_grade(entry.accuracy)
        songs.append({
            "jacket": jacket_map.get(entry.song_id),
            "difficulty": entry.difficulty.value,
            "level": entry.official_level,
            "displayLevel": entry.official_level,
            "title": entry.song_title,
            "status": 2 if ap else 1,
            "achievementRate": None if ap else entry.accuracy,
            "power": entry.rating,
            "gradeLabel": grade_label,
            "gradeClass": grade_class,
            "judges": {
                "great": entry.judgements.great,
                "good": entry.judgements.good,
                "bad": entry.judgements.bad,
                "miss": entry.judgements.miss,
            },
        })

    return {
        "b20": songs,
        "sp": result.sp,
        "b20Avg": result.b20_avg,
        "fcBonus": result.fc_bonus,
        "masterBonus": result.ap_bonus,
        "playerClass": {
            "name": result.player_class.name,
            "icon": result.player_class.icon,
            "stars": result.player_class.stars,
            "fallbackColor": result.player_class.fallback_color,
        },
        "isAppendExcluded": result.append_excluded,
        "currentPercentile": 0,
        "displayRank": "",
    }


def _build_ranking_payload(
    ranking: "DifficultyRanking",
    jacket_map: dict[int, str],
) -> dict[str, object]:
    """Assemble the COMPLETE JS payload for difficulty.js.

    Every field the JS renderer reads is explicitly assigned here.
    """
    _DIFF_ABBREV: dict[str, str] = {
        "master": "MA", "expert": "EX", "append": "APD",
        "hard": "HD", "normal": "NM", "easy": "EZ",
    }

    tiers: list[dict[str, object]] = []
    current_constant: str | None = None
    current_songs: list[dict[str, object]] = []

    for entry in ranking.entries:
        if entry.community_constant != current_constant:
            if current_songs:
                tiers.append({
                    "constant_label": current_constant or "0.0",
                    "songs": current_songs,
                })
            current_constant = entry.community_constant
            current_songs = []

        status: int = 0
        judges: dict[str, int] | None = None
        acc: float = 0.0
        power: float = 0.0
        if entry.personal_best is not None:
            pb = entry.personal_best
            if pb.status == ScoreStatus.AP:
                status = 2
            elif pb.status == ScoreStatus.FC:
                status = 1
            judges = {
                "great": pb.judgements.great,
                "good": pb.judgements.good,
                "bad": pb.judgements.bad,
                "miss": pb.judgements.miss,
            }
            acc = pb.accuracy
            power = pb.rating

        current_songs.append({
            "jacket": jacket_map.get(entry.song_id),
            "status": status,
            "judges": judges,
            "accuracy": acc,
            "power": power,
        })

    if current_songs:
        tiers.append({
            "constant_label": current_constant or "0.0",
            "songs": current_songs,
        })

    abbrev = _DIFF_ABBREV.get(ranking.difficulty.value, ranking.difficulty.value.upper())

    return {
        "mode": ranking.mode,
        "title": f"{abbrev} {ranking.official_level}",
        "tiers": tiers,
    }


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

    # ── Assemble complete JS payload → render image → fallback text ──
    png: bytes | None = None
    if runtime.renderer is not None:
        try:
            from pjsk_core.application.render_b20 import render_b20

            # Resolve jacket HTTP URLs
            song_ids = [e.song_id for e in b20_result.entries]
            jacket_map: dict[int, str] = {}
            if runtime.jacket_cache is not None:
                for sid in song_ids:
                    url = await runtime.jacket_cache.ensure_jacket_file_url(sid)
                    if url is not None:
                        jacket_map[sid] = url

            _logger.info(
                "B20 render: entries=%d jackets=%d/%d",
                len(b20_result.entries), len(jacket_map), len(song_ids),
            )
            data = _build_b20_payload(b20_result, jacket_map)
            png = await render_b20(data, renderer=runtime.renderer)
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
    difficulty: str | None = None,
) -> None:
    """Return personal difficulty ranking."""
    if _runtime is None or level is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用"))
        return

    from pjsk_core.domain.charts import Difficulty
    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    diff = Difficulty(difficulty) if difficulty else Difficulty.MASTER

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
            user.id, diff, level,
        )
    except Exception:
        _logger.exception("Personal difficulty ranking failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    diff_label = difficulty.upper() if difficulty else "MA"

    if not ranking.entries:
        await send_text_reply(bot, event, TextReply(text=f"{diff_label} {level} 暂无成绩"))
        return

    # ── Assemble JS payload → render image → fallback text ──
    png: bytes | None = None
    if runtime.renderer is not None:
        try:
            from pjsk_core.application.render_difficulty_ranking import (
                render_difficulty_ranking,
            )

            # Resolve jacket HTTP URLs
            song_ids = [e.song_id for e in ranking.entries]
            jacket_map: dict[int, str] = {}
            if runtime.jacket_cache is not None:
                for sid in song_ids:
                    url = await runtime.jacket_cache.ensure_jacket_file_url(sid)
                    if url is not None:
                        jacket_map[sid] = url

            data = _build_ranking_payload(ranking, jacket_map)
            png = await render_difficulty_ranking(data, renderer=runtime.renderer)
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
        lines = [f"个人 {diff_label} {level} 排行", ""]
        for i, e in enumerate(ranking.entries[:20], 1):
            status_str = e.status.value.upper() if e.status else "未游玩"
            acc_str = f"ACC {e.accuracy:.2f}%" if e.accuracy is not None else ""
            rating_str = f"Rating {e.rating:.2f}" if e.rating is not None else ""
            parts = [f"[{i}] {e.song_title}", status_str, acc_str, rating_str]
            lines.append(" · ".join(p for p in parts if p))
        await send_text_reply(bot, event, TextReply(text="\n".join(lines)))


async def _handle_global_difficulty(
    bot: Bot, event: MessageEvent, msg: IncomingMessage, level: int | None,
    difficulty: str | None = None,
) -> None:
    """Return global difficulty ranking."""
    if _runtime is None or level is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用"))
        return

    from pjsk_core.domain.charts import Difficulty
    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    diff = Difficulty(difficulty) if difficulty else Difficulty.MASTER
    diff_label = difficulty.upper() if difficulty else "MA"

    try:
        ranking = await runtime.query_difficulty_ranking.query_global(
            diff, level,
        )
    except Exception:
        _logger.exception("Global difficulty ranking failed")
        await send_text_reply(bot, event, TextReply(text="查询失败，请稍后重试"))
        return

    if not ranking.entries:
        await send_text_reply(bot, event, TextReply(text=f"{diff_label} {level} 暂无排行数据"))
        return

    # ── Assemble JS payload → render image → fallback text ──
    png: bytes | None = None
    if runtime.renderer is not None:
        try:
            from pjsk_core.application.render_difficulty_ranking import (
                render_difficulty_ranking,
            )

            # Resolve jacket HTTP URLs
            song_ids = [e.song_id for e in ranking.entries]
            jacket_map: dict[int, str] = {}
            if runtime.jacket_cache is not None:
                for sid in song_ids:
                    url = await runtime.jacket_cache.ensure_jacket_file_url(sid)
                    if url is not None:
                        jacket_map[sid] = url

            data = _build_ranking_payload(ranking, jacket_map)
            png = await render_difficulty_ranking(data, renderer=runtime.renderer)
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
        lines = [f"{diff_label} {level} 全局排行（定数降序）", ""]
        for i, e in enumerate(ranking.entries[:20], 1):
            lines.append(
                f"[{i}] {e.song_title} · 定数 {e.community_constant} · "
                f"{diff_label} {e.official_level}"
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
