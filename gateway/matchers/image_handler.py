"""NoneBot matcher for image/OCR — private direct, group stores for .emu trigger."""
from __future__ import annotations

import logging
from typing import Any, NamedTuple

import httpx
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.rule import Rule

from pjsk_core.application.recognize_score import RecognizeResult
from pjsk_core.application.replies import ImageReply, TextReply
from pjsk_core.application.vision_race import EngineResultStatus, VisionRaceDecision
from pjsk_core.domain.users import QqNumber, User
from gateway.commands import qq_allowed
from gateway.adapters.event_mapper import IncomingMessage, map_event
from gateway.adapters.reply_sender import send_text_reply
from gateway.matchers.pending_image_store import PendingImageStore

_logger = logging.getLogger(__name__)

# Module-level pending-image store — shared with command_handler
_pending_store = PendingImageStore()


def get_pending_store() -> PendingImageStore:
    """Return the module-level PendingImageStore for use by command_handler."""
    return _pending_store

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
    """Private: any image triggers OCR.  Group: any image is stored for .emu."""
    has_image = any(seg.type == "image" for seg in event.message)
    if not has_image:
        return False
    # Group: store ALL images (no @Bot needed — .emu command handles the trigger)
    # Private: OCR immediately
    return True


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
    labels: dict[object, str] = {
        Difficulty.EASY: "EASY", Difficulty.NORMAL: "NORMAL",
        Difficulty.HARD: "HARD", Difficulty.EXPERT: "EXPERT",
        Difficulty.MASTER: "MASTER", Difficulty.APPEND: "APPEND",
    }
    return labels.get(difficulty, str(difficulty))


def _status_label(status: object) -> str:
    from pjsk_core.domain.scores import ScoreStatus
    labels: dict[object, str] = {
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


class _CandidateEntry(NamedTuple):
    """Resolved display data for one OCR candidate."""
    song_title: str       # resolved from chart/song
    difficulty: str       # e.g. "MA"
    level: int
    constant: str         # e.g. "30.2+"
    confidence: float     # title similarity 0–1
    note_distance: int
    model_support: int
    note_count: int       # from chart, 0 if unresolved
    chart_id: int | None


def _format_candidates_text(
    result: RecognizeResult,
    *,
    chart_details: dict[int, tuple[str, str, int, str, int]] | None = None,
) -> str:
    """Format disagreement candidates as a dual-rank pick list.

    **Rank 1 — 歌名匹配最佳** (by title similarity, max 5).
    **Rank 2 — Note总数最接近** (by note-distance, max 5, excludes rank‑1).
    Unified numbering across both ranks.
    """
    candidates = list(result.candidates_for_user)
    if not candidates:
        return "多模型识别不一致，请重新发送截图"

    details = chart_details or {}

    # OCR total note count
    obs0 = candidates[0].observation
    ocr_total = sum([
        obs0.judgements.perfect, obs0.judgements.great,
        obs0.judgements.good, obs0.judgements.bad, obs0.judgements.miss,
    ])

    # ── Build entries ────────────────────────────────────────────────────
    entries: list[_CandidateEntry] = []
    for c in candidates:
        cd = details.get(c.matched_chart_id) if c.matched_chart_id else None
        if cd is not None:
            song_title, diff_str, level, constant, note_count = cd
        else:
            obs = c.observation
            song_title = obs.song_title
            diff_str = _diff_label(obs.difficulty)
            level = obs.displayed_level
            constant = "?"
            note_count = 0
        entries.append(_CandidateEntry(
            song_title=song_title, difficulty=diff_str, level=level,
            constant=constant, confidence=c.title_similarity,
            note_distance=c.note_distance, model_support=c.model_support,
            note_count=note_count, chart_id=c.matched_chart_id,
        ))

    # ── Rank 1: 歌名匹配最佳 ─────────────────────────────────────────────
    rank1 = sorted(entries, key=lambda e: -e.confidence)[:5]
    rank1_keys = {(e.difficulty, e.level, e.chart_id) for e in rank1}

    # ── Rank 2: Note总数最接近 (exclude rank‑1) ──────────────────────────
    rank2 = sorted(
        [e for e in entries if (e.difficulty, e.level, e.chart_id) not in rank1_keys],
        key=lambda e: e.note_distance,
    )[:5]

    # ── Merge with unified numbering ─────────────────────────────────────
    all_items: list[tuple[str, _CandidateEntry]] = []
    for e in rank1:
        all_items.append(("match", e))
    for e in rank2:
        all_items.append(("note", e))

    lines = ["⚠️ 多模型识别不一致，请回复数字选择（30s）：", ""]

    if rank1:
        lines.append("▎歌名匹配最佳")
    for idx, (kind, e) in enumerate(all_items):
        if kind == "note" and idx > 0 and all_items[idx - 1][0] == "match":
            lines.append("")
            lines.append(f"▎Note总数最接近 (OCR: {ocr_total})")
        num = idx + 1
        diff_info = f"{e.difficulty} {e.level}"
        if e.constant != "?":
            diff_info += f" 定数{e.constant}"
        models = f" 模型×{e.model_support}"
        if kind == "match":
            lines.append(
                f"  {num}. {e.song_title} [{diff_info}] "
                f"({e.confidence * 100:.1f}%){models}"
            )
        else:
            if e.note_count:
                lines.append(
                    f"  {num}. {e.song_title} [{diff_info}] "
                    f"({e.note_count} notes, 差{e.note_distance}){models}"
                )
            else:
                lines.append(
                    f"  {num}. {e.song_title} [{diff_info}] "
                    f"(OCR:{ocr_total} notes){models}"
                )

    return "\n".join(lines)


# ── Engine diagnostics ───────────────────────────────────────────────────────


def _log_engine_results(result: RecognizeResult) -> None:
    """Log per-engine status so operators can distinguish consensus vs degraded."""
    outcome = result.outcome
    total = len(outcome.results)
    succeeded = [r for r in outcome.results if r.status == EngineResultStatus.SUCCESS]
    failed = [r for r in outcome.results if r.status != EngineResultStatus.SUCCESS]

    parts = [f"decision={outcome.decision.value}", f"engines={total}"]
    if succeeded:
        parts.append(
            "ok=" + ",".join(
                f"{r.identity.engine_id}({r.elapsed_ms}ms)"
                for r in succeeded
            )
        )
    if failed:
        parts.append(
            "fail=" + ",".join(
                f"{r.identity.engine_id}({r.status.value})"
                for r in failed
            )
        )
    if outcome.circuit_rejects:
        parts.append(f"circuit_rejects={len(outcome.circuit_rejects)}")

    _logger.info("OCR done: %s", " | ".join(parts))


# ── Handler ──────────────────────────────────────────────────────────────────


# ── PJSK_OCR_READONLY ────────────────────────────────────────────────────────
# Environment variable controlling persistence:
#   "1" (or any truthy value) — identify only, NEVER write to database.
#   unset / "0"                — production mode: consensus → auto-save,
#                                disagreement → store candidates for user pick.
# Shadow verification uses "1"; normal operation leaves it unset.


@image_matcher.handle()
async def _handle_image(bot: Bot, event: MessageEvent) -> None:
    """Handle image messages.

    Private: OCR immediately, reply with text (future: render image).
    Group:   store image in PendingImageStore, confirm with a short text.
    """
    import os

    msg = map_event(event)

    if not qq_allowed(msg.external_user_id):
        return

    # ── Group chat: store image for later .emu trigger ──────────────────────
    if event.message_type == "group":
        async with httpx.AsyncClient(timeout=30.0) as client:
            image_data = await _download_image(event, bot, client)
        if image_data is None:
            await send_text_reply(bot, event, TextReply(text="图片下载失败，请重新发送"))
            return
        error = _validate_image(image_data)
        if error is not None:
            await send_text_reply(bot, event, TextReply(text=error))
            return
        group_id = str(getattr(event, "group_id", "0"))
        qq_str = msg.external_user_id
        _pending_store.put(group_id, qq_str, image_data)
        _logger.info(
            "image stored: group=%s qq=%s size=%d",
            group_id, qq_str, len(image_data),
        )
        # Silent storage — user triggers OCR later with .emu
        return

    # ── Private chat: full OCR flow ─────────────────────────────────────────
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
        _log_engine_results(result)
        if result.score_attempt is not None and not readonly:
            pb = await runtime.score_repo.get_personal_best(user.id, result.score_attempt.chart_id)
            old_pb_rating = pb.rating if pb is not None and pb.id != result.score_attempt.id else None
    except Exception:
        _logger.exception("OCR failed")
        await send_text_reply(bot, event, TextReply(text="识别失败，请稍后重试"))
        return

    # Format and reply
    decision = result.outcome.decision
    if decision in (VisionRaceDecision.CONSENSUS, VisionRaceDecision.DEGRADED_SINGLE):
        _logger.info("OCR private: calling _try_render_ocr_card decision=%s", decision.value)
        png = await _try_render_ocr_card(
            result, runtime, msg, old_pb_rating, readonly,
        )
        if png is not None:
            from gateway.adapters.reply_sender import send_image_reply
            await send_image_reply(
                bot, event,
                ImageReply(image_bytes=png, mime_type="image/png"),
            )
            # Append PB update note as text after the image
            if not readonly and result.score_attempt is not None:
                if old_pb_rating is None:
                    await send_text_reply(
                        bot, event, TextReply(text="新曲目，已记录"),
                    )
                else:
                    await send_text_reply(
                        bot, event,
                        TextReply(
                            text=f"已记录（原个人最佳: {old_pb_rating:.2f}）",
                        ),
                    )
            return  # ← Image reply sent; do NOT fall through to text send below
        else:
            if readonly:
                text = (
                    _format_readonly_result(result)
                    if result.validated is not None
                    else "识别完成但无法解析结果"
                )
            else:
                text = _format_consensus_reply(result, old_pb_rating)
            await send_text_reply(bot, event, TextReply(text=text))
            return  # ← Text fallback sent; do NOT fall through to duplicate text send
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

    # Non-consensus branches all produce text-only replies
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


async def _try_render_ocr_card(
    result: RecognizeResult,
    runtime: object,  # Runtime — avoid circular import
    msg: object,      # IncomingMessage
    old_pb_rating: float | None,
    readonly: bool,
) -> bytes | None:
    """Try to render an OCR result card. Returns PNG bytes or None.

    The ``validated.primary`` field may be None even when
    ``score_attempt`` was saved (the two success checks are not the
    same).  This function tries multiple data sources:

    1. ``validated.primary.chart`` (preferred — has authoritative data)
    2. ``score_attempt.chart_id`` → lookup via ``ChartRepository``
    3. Fall back to ``OcrObservation`` fields

    Returns None if rendering is impossible or fails.
    """
    from pjsk_runtime.runtime import Runtime
    rt: Runtime = runtime  # type: ignore[assignment]

    validated = result.validated
    attempt = result.score_attempt

    # Diagnostic log — which fields are present?
    has_primary = validated is not None and validated.primary is not None
    has_attempt = attempt is not None
    has_renderer = rt.renderer is not None
    _logger.info(
        "ocr_render_gate validated=%s primary=%s attempt=%s renderer=%s",
        validated is not None,
        has_primary,
        has_attempt,
        has_renderer,
    )

    if not has_renderer or not has_attempt:
        return None

    assert attempt is not None  # type-narrowing
    assert rt.renderer is not None  # type-narrowing (guarded by has_renderer above)

    # ── Resolve chart / song metadata ──────────────────────────────────
    obs = validated.observation if validated is not None else None
    chart = (
        validated.primary.chart  # type: ignore[union-attr]
        if has_primary
        else None
    )

    if chart is None and attempt.chart_id > 0:
        try:
            chart = await rt.chart_repo.get_by_id(attempt.chart_id)
        except Exception:
            _logger.exception("Chart lookup failed for OCR render")

    song_id = chart.song_id if chart else 0
    # Try to get title from chart's song repo
    title_ja = ""
    if chart is not None:
        try:
            song = await rt.song_repo.get_by_id(chart.song_id)
            title_ja = song.title_ja if song else ""
        except Exception:
            pass
    if not title_ja and obs is not None:
        title_ja = obs.song_title or ""

    difficulty = chart.difficulty.value if chart else (obs.difficulty.value if obs else "unknown")
    level = chart.official_level if chart else (obs.displayed_level if obs else 0)
    constant = chart.community_constant if chart else ""

    # ── Jacket ─────────────────────────────────────────────────────────
    jacket_url: str | None = None
    if song_id > 0 and rt.jacket_cache is not None:
        try:
            jacket_url = await rt.jacket_cache.get_jacket(song_id)
        except Exception:
            pass

    # ── Compute SP (B20 average) via existing QueryB20 use case ────────
    # Called AFTER score is saved, so the result includes the just-inserted
    # attempt. Falls back to "—" on any failure.
    sp_value = "—"
    try:
        if rt.query_b20 is not None:
            b20_result = await rt.query_b20.query(attempt.user_id)
            sp_value = f"{b20_result.b20_avg:.1f}" if b20_result.entries else "0.0"
    except Exception:
        _logger.warning("Failed to query B20 for OCR card SP", exc_info=True)

    # ── Lookup Chinese song title ──────────────────────────────────────
    title_cn = ""
    if chart is not None:
        try:
            song = await rt.song_repo.get_by_id(chart.song_id)
            title_cn = song.title_cn if song and song.title_cn else ""
        except Exception:
            pass

    # ── Build render payload ───────────────────────────────────────────
    from pjsk_core.application.render_ocr_card import render_ocr_card

    try:
        png = await render_ocr_card(
            song_id=song_id,
            title_ja=title_ja,
            title_cn=title_cn,
            difficulty=difficulty,
            level=level,
            constant=constant,
            accuracy=attempt.accuracy,
            rating=attempt.rating,
            sp=sp_value,
            perfect=attempt.judgements.perfect,
            great=attempt.judgements.great,
            good=attempt.judgements.good,
            bad=attempt.judgements.bad,
            miss=attempt.judgements.miss,
            status=attempt.status.value,
            qq_id=msg.external_user_id if hasattr(msg, "external_user_id") else "",
            jacket_data_url=jacket_url,
            renderer=rt.renderer,
        )
        return png
    except Exception:
        _logger.exception("OCR card render failed in _try_render_ocr_card")
        return None


async def _handle_disagreement(
    result: RecognizeResult, user: User, msg: IncomingMessage, runtime: object,
) -> str:
    """Store candidates and return a dual-rank pick-list for user selection."""
    from pjsk_runtime.runtime import Runtime
    rt: Runtime = runtime  # type: ignore[assignment]

    if not result.candidates_for_user or result.candidate_set_id is None:
        return "多模型识别不一致，请重新发送截图"

    # ── Resolve chart + song details for rich display ────────────────────
    # chart_id → (song_title, difficulty_label, official_level, constant, note_count)
    chart_details: dict[int, tuple[str, str, int, str, int]] = {}
    if rt.chart_repo is not None:
        for c in result.candidates_for_user:
            cid = c.matched_chart_id
            if cid is None or cid in chart_details:
                continue
            try:
                chart = await rt.chart_repo.get_by_id(cid)
            except Exception:
                _logger.warning("Chart lookup failed for chart_id=%d", cid)
                continue
            if chart is None:
                continue
            # Resolve song title
            song_title = f"chart#{cid}"
            if rt.song_repo is not None:
                try:
                    song = await rt.song_repo.get_by_id(chart.song_id)  # type: ignore[arg-type]
                    if song is not None:
                        song_title = song.title_cn or song.title_ja or song_title
                except Exception:
                    pass
            chart_details[cid] = (
                song_title,
                _diff_label(chart.difficulty),
                chart.official_level,
                chart.community_constant,
                chart.note_count,
            )

    cid = result.candidate_set_id
    display = _format_candidates_text(result, chart_details=chart_details)

    # Store pending candidate reference
    conv_id = msg.group_id if msg.group_id else f"private_{msg.external_user_id}"
    rt.set_pending(user.id.value, "onebot", conv_id, cid, display)

    return display
