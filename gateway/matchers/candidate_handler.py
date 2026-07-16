"""NoneBot matcher for candidate confirmation — user replies with a number."""
from __future__ import annotations

import logging
import re

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.rule import Rule

from pjsk_core.application.replies import TextReply
from pjsk_core.domain.scores import ScoreAttempt
from pjsk_core.domain.users import QqNumber
from gateway.adapters.event_mapper import map_event
from gateway.adapters.reply_sender import send_text_reply
from gateway.commands import qq_allowed

_logger = logging.getLogger(__name__)

# Match user input that looks like a candidate selection number (1-9, or "选 1")
_SELECTION_RE = re.compile(r"^(?:选\s*)?(\d+)$")

# Runtime injection
_runtime: object | None = None


def set_candidate_runtime(runtime: object) -> None:
    """Register the Runtime so candidate matcher can access use cases."""
    global _runtime
    _runtime = runtime


async def _is_candidate_selection(event: MessageEvent) -> bool:
    """Trigger when user sends a pure number and may have pending candidates."""
    if _runtime is None:
        return False
    text = event.get_plaintext().strip()
    return bool(_SELECTION_RE.match(text))


candidate_matcher = on_message(
    rule=Rule(_is_candidate_selection), priority=5, block=False,
)


def _format_confirm_result(attempt: ScoreAttempt) -> str:
    """Format a confirmed score result."""
    from gateway.matchers.image_handler import _status_label

    j = attempt.judgements
    lines = [
        "已确认成绩",
        f"PERFECT：{j.perfect}",
        f"GREAT：{j.great}",
        f"GOOD：{j.good}",
        f"BAD：{j.bad}",
        f"MISS：{j.miss}",
        f"状态：{_status_label(attempt.status)}",
        f"ACC：{attempt.accuracy:.4f}%",
        f"Rating：{attempt.rating:.2f}",
    ]
    return "\n".join(lines)


@candidate_matcher.handle()
async def _handle_selection(bot: Bot, event: MessageEvent) -> None:
    """Handle candidate selection — number confirmation."""
    from pjsk_runtime.runtime import Runtime

    msg = map_event(event)

    if not qq_allowed(msg.external_user_id):
        return

    runtime: Runtime = _runtime  # type: ignore[assignment]
    if runtime is None:
        return

    # Parse selection number
    text = event.get_plaintext().strip()
    m = _SELECTION_RE.match(text)
    if m is None:
        return
    selection = int(m.group(1))

    # Look up pending candidates for this user+conversation
    qq = QqNumber(msg.external_user_id)
    user = await runtime.user_repo.get_by_qq(qq)
    if user is None:
        return  # not registered, ignore quietly

    conv_id = msg.group_id or f"private_{msg.external_user_id}"
    cid = runtime.get_pending_candidate_set_id(user.id.value, "onebot", conv_id)
    if cid is None:
        return  # no pending candidates, ignore (not a selection)

    # Confirm
    if runtime.confirm_candidate is None:
        await send_text_reply(bot, event, TextReply(text="确认功能暂未开放"))
        return

    _logger.info("candidate selection: user=%d selection=%d cid=%s", user.id.value, selection, cid)
    try:
        confirm_result = await runtime.confirm_candidate.confirm(
            user.id, cid, selection,
        )
    except Exception:
        _logger.exception("Candidate confirmation failed")
        runtime.clear_pending(user.id.value, "onebot", conv_id)
        await send_text_reply(bot, event, TextReply(text="确认失败，请重新发送截图"))
        return

    if confirm_result.error is not None:
        error_msgs = {
            "not_found": "该候选已失效，请重新发送截图",
            "expired": "候选已过期，请重新发送截图",
            "forbidden": "该候选不属于你",
            "invalid_selection": "无效的编号，请重新选择",
            "not_confirmable": "该候选无法确认（谱面或判定校验失败）",
        }
        msg_text = error_msgs.get(
            confirm_result.error.value,
            f"确认失败: {confirm_result.error.value}",
        )
        await send_text_reply(bot, event, TextReply(text=msg_text))
        return

    # Success — clear pending and reply
    runtime.clear_pending(user.id.value, "onebot", conv_id)
    if confirm_result.score_attempt is not None:
        reply = _format_confirm_result(confirm_result.score_attempt)
        await send_text_reply(bot, event, TextReply(text=reply))
    else:
        await send_text_reply(bot, event, TextReply(text="已确认"))
