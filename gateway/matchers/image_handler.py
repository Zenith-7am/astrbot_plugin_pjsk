"""NoneBot matcher for image/OCR — private direct, group @Bot trigger."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.rule import Rule

from pjsk_core.application.recognize_score import RecognizeResult
from pjsk_core.application.replies import TextReply
from pjsk_core.application.vision_race import VisionRaceDecision
from pjsk_core.domain.users import QqNumber, User
from gateway.commands import qq_allowed
from gateway.adapters.event_mapper import IncomingMessage, map_event
from gateway.adapters.reply_sender import send_text_reply

_logger = logging.getLogger(__name__)

# ── Image validation ─────────────────────────────────────────────────────────

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB
IMAGE_TIMEOUT = 15.0  # seconds

_MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",
}


def _validate_image(data: bytes) -> str | None:
    """Check image format and size. Returns error message or None if ok."""
    if len(data) > MAX_IMAGE_BYTES:
        return "图片过大，请压缩后重试（最大 10 MiB）"
    if len(data) < 8:
        return "图片数据不完整，请重新发送"

    for magic, ext in _MAGIC_BYTES.items():
        if data.startswith(magic):
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            if len(data) < 100:
                return "图片数据不完整，请发送原图"
            return None  # valid

    return "图片格式不支持，请发送 JPEG/PNG/GIF/WebP 格式"


# ── Image download ───────────────────────────────────────────────────────────


async def _download_image(
    event: MessageEvent, bot: Bot, http_client: httpx.AsyncClient,
) -> bytes | None:
    """Download the first image in the message. Returns bytes or None on failure."""
    for seg in event.message:
        if seg.type != "image":
            continue

        url = seg.data.get("url", "")
        file_id = seg.data.get("file", "")

        # No direct URL → fetch via OneBot protocol
        if not url and file_id:
            try:
                resp_data: dict[str, Any] = await bot.get_image(file=file_id)
                inner = (
                    resp_data.get("data", resp_data)
                    if isinstance(resp_data, dict)
                    else resp_data
                )
                if isinstance(inner, dict):
                    url = inner.get("url", "") or inner.get("file", "")
            except Exception:
                _logger.debug("get_image API failed for file_id=%s", file_id)
                continue

        if not url:
            _logger.debug("No URL from image segment")
            continue

        try:
            async with http_client.stream(
                "GET", url,
                timeout=httpx.Timeout(IMAGE_TIMEOUT),
                follow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("Content-Length")
                if content_length is not None and int(content_length) > MAX_IMAGE_BYTES:
                    _logger.info("image too large: %s bytes", content_length)
                    return None

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        _logger.info("image exceeded limit during streaming")
                        return None

                return b"".join(chunks)
        except httpx.TimeoutException:
            _logger.info("image download timed out")
            return None
        except Exception:
            _logger.debug("image download failed", exc_info=True)
            return None

    return None


# ── Trigger rule ─────────────────────────────────────────────────────────────


async def _image_trigger(event: MessageEvent) -> bool:
    """Private: any image triggers.  Group: only @Bot + image triggers."""
    has_image = any(seg.type == "image" for seg in event.message)
    if not has_image:
        return False
    if event.message_type == "private":
        return True
    return bool(getattr(event, "to_me", False))


image_matcher = on_message(rule=Rule(_image_trigger), priority=10, block=False)


# ── Runtime access ───────────────────────────────────────────────────────────

_runtime: object | None = None


def set_image_runtime(runtime: object) -> None:
    """Register the Runtime so image matcher can call use cases."""
    global _runtime
    _runtime = runtime


# ── Text formatting ──────────────────────────────────────────────────────────


def _diff_label(difficulty: object) -> str:
    from pjsk_core.domain.charts import Difficulty
    labels = {
        Difficulty.EASY: "EASY", Difficulty.NORMAL: "NORMAL",
        Difficulty.HARD: "HARD", Difficulty.EXPERT: "EXPERT",
        Difficulty.MASTER: "MASTER", Difficulty.APPEND: "APPEND",
    }
    return labels.get(difficulty, str(difficulty))


def _status_label(status: object) -> str:
    from pjsk_core.domain.scores import ScoreStatus
    labels = {
        ScoreStatus.AP: "AP", ScoreStatus.FC: "FC",
        ScoreStatus.CLEAR: "CLEAR",
    }
    return labels.get(status, str(status))


def _format_readonly_result(result: RecognizeResult) -> str:
    """Format a read-only OCR result as human-readable text."""
    if result.validated is None or result.validated.primary is None:
        return "无法解析识别结果，请重试"

    obs = result.validated.observation
    j = obs.judgements
    attempt = result.score_attempt

    lines = [
        "识别结果",
        f"曲目：{obs.song_title or '(未知)'}",
        f"难度：{_diff_label(obs.difficulty)} {obs.displayed_level}",
        f"PERFECT：{j.perfect}",
        f"GREAT：{j.great}",
        f"GOOD：{j.good}",
        f"BAD：{j.bad}",
        f"MISS：{j.miss}",
    ]

    if attempt is not None:
        lines.append(f"状态：{_status_label(attempt.status)}")
        lines.append(f"ACC：{attempt.accuracy:.4f}%")
        lines.append(f"Rating：{attempt.rating:.2f}")

    primary = result.validated.primary
    if primary.chart is not None and primary.chart.community_constant:
        lines.append(f"定数：{primary.chart.community_constant}")

    if result.outcome.decision == VisionRaceDecision.CONSENSUS:
        lines.append("（多模型共识）")
    elif result.outcome.decision == VisionRaceDecision.DEGRADED_SINGLE:
        lines.append("（单模型识别）")

    return "\n".join(lines)


def _format_candidates_text(result: RecognizeResult) -> str:
    """Format disagreement candidates as text for user review."""
    if not result.candidates_for_user:
        return "多模型识别不一致，请重新发送截图"

    lines = ["多模型识别不一致，候选结果：", ""]
    for i, c in enumerate(result.candidates_for_user, 1):
        obs = c.observation
        j = obs.judgements
        lines.append(
            f"[{i}] {obs.song_title} · "
            f"{_diff_label(obs.difficulty)} {obs.displayed_level} · "
            f"P:{j.perfect} G:{j.great} Go:{j.good} B:{j.bad} M:{j.miss}"
        )
        if c.matched_chart_id is not None:
            lines[-1] += f" · 定数(chart#{c.matched_chart_id})"
        lines[-1] += f" · 模型支持:{c.model_support}"

    lines.append("")
    lines.append("候选确认功能将在后续版本开放")
    return "\n".join(lines)


# ── Handler ──────────────────────────────────────────────────────────────────


@image_matcher.handle()
async def _handle_image(bot: Bot, event: MessageEvent) -> None:
    """Handle image OCR.

    Consensus → auto-save score.  Disagreement → store candidates for user pick.
    Set ``PJSK_OCR_READONLY=1`` in environment to skip persistence (shadow mode).
    """
    import os

    msg = map_event(event)

    if not qq_allowed(msg.external_user_id):
        return

    if _runtime is None:
        await send_text_reply(bot, event, TextReply(text="服务正在启动中，请稍后再试"))
        return

    from pjsk_runtime.runtime import Runtime
    runtime: Runtime = _runtime  # type: ignore[assignment]

    # Resolve user — must be registered
    qq = QqNumber(msg.external_user_id)
    user: User | None = None
    try:
        user = await runtime.user_repo.get_by_qq(qq)
    except Exception:
        _logger.exception("User lookup failed")
        await send_text_reply(bot, event, TextReply(text="服务异常，请稍后重试"))
        return

    if user is None:
        await send_text_reply(bot, event, TextReply(text="请先使用 /emu register 注册"))
        return

    # Check OCR capability
    if runtime.recognize_score is None:
        await send_text_reply(bot, event, TextReply(text="识别服务暂未开放"))
        return
    if runtime.http_client is None:
        await send_text_reply(bot, event, TextReply(text="服务暂不可用，请稍后重试"))
        return

    # Download image
    image_data = await _download_image(event, bot, runtime.http_client)
    if image_data is None:
        await send_text_reply(bot, event, TextReply(text="图片下载失败，请重新发送"))
        return

    # Validate
    error = _validate_image(image_data)
    if error is not None:
        await send_text_reply(bot, event, TextReply(text=error))
        return

    # OCR — snapshot old PB before recognize (for "刷新个人最佳" status)
    readonly = os.environ.get("PJSK_OCR_READONLY") == "1"
    old_pb_rating: float | None = None
    _logger.info(
        "image received: type=%s size=%d readonly=%s",
        msg.conversation_type.value, len(image_data), readonly,
    )
    try:
        result = await runtime.recognize_score.recognize(
            user.id, image_data, source_gateway="onebot", readonly=readonly,
        )
        # Capture old PB *after* recognize in case of race (rare, cosmetic impact)
        if result.score_attempt is not None and not readonly:
            pb = await runtime.score_repo.get_personal_best(user.id, result.score_attempt.chart_id)
            # If the current PB is ours (same attempt id), check if there was a previous one
            old_pb_rating = pb.rating if pb is not None and pb.id != result.score_attempt.id else None
    except Exception:
        _logger.exception("OCR failed")
        await send_text_reply(bot, event, TextReply(text="识别失败，请稍后重试"))
        return

    # Format and reply
    decision = result.outcome.decision
    if decision in (VisionRaceDecision.CONSENSUS, VisionRaceDecision.DEGRADED_SINGLE):
        if readonly:
            text = _format_readonly_result(result) if result.validated is not None else "识别完成但无法解析结果"
        else:
            text = _format_consensus_reply(result, old_pb_rating)
    elif decision == VisionRaceDecision.DISAGREEMENT:
        if readonly:
            text = _format_candidates_text(result)
        else:
            text = await _handle_disagreement(result, user, msg, runtime)
    elif decision == VisionRaceDecision.ALL_FAILED:
        text = "所有识别模型均失败，请稍后重试"
    elif decision == VisionRaceDecision.NO_AVAILABLE_ENGINES:
        text = "识别服务未配置，请联系管理员"
    elif decision == VisionRaceDecision.GLOBAL_TIMEOUT:
        text = "识别超时，请重新发送"
    else:
        text = "识别失败，请稍后重试"

    await send_text_reply(bot, event, TextReply(text=text))


def _format_consensus_reply(
    result: RecognizeResult, old_pb_rating: float | None,
) -> str:
    """Format consensus result with PB update status."""
    if result.score_attempt is None or result.validated is None:
        return "识别完成但无法保存"

    lines = [_format_readonly_result(result)]
    if result.score_attempt.rating > 0:  # valid rating → was saved
        if old_pb_rating is None:
            lines.append("")
            lines.append("新曲目，已记录")
        else:
            lines.append("")
            lines.append(f"已记录（原个人最佳: {old_pb_rating:.2f}）")
    return "\n".join(lines)


async def _handle_disagreement(
    result: RecognizeResult, user: User, msg: IncomingMessage, runtime: object,
) -> str:
    """Store candidates and return a pick list."""
    from pjsk_runtime.runtime import Runtime
    rt: Runtime = runtime  # type: ignore[assignment]

    if not result.candidates_for_user or result.candidate_set_id is None:
        return "多模型识别不一致，请重新发送截图"

    cid = result.candidate_set_id
    display = _format_candidates_text(result)

    # Store pending candidate reference
    conv_id = msg.group_id if msg.group_id else f"private_{msg.external_user_id}"
    rt.set_pending(user.id.value, "onebot", conv_id, cid, display)

    return display
