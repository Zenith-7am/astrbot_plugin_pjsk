"""NoneBot matcher for /emu — imports pure functions from gateway.commands."""
from __future__ import annotations

import logging

import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from pjsk_core.application.replies import TextReply
from pjsk_core.domain.users import QqNumber
from gateway.commands import (
    EmuCommand,
    build_help_text,
    build_status_text,
    parse_emu_command,
    qq_allowed,
)
from gateway.adapters.event_mapper import IncomingMessage, map_event
from gateway.adapters.reply_sender import send_text_reply

_logger = logging.getLogger(__name__)

emu_cmd = on_command("emu", priority=20, block=True)

# Injected by bootstrap after Runtime assembly.
# The command handler reads this to access use cases.
_runtime: object | None = None


def set_runtime_for_commands(runtime: object) -> None:
    """Register the Runtime so matchers can call use cases."""
    global _runtime
    _runtime = runtime


@emu_cmd.handle()
async def _emu(bot: Bot, event: MessageEvent) -> None:
    msg = map_event(event)

    # Test allowlist — when set, only listed QQ numbers get replies
    if not qq_allowed(msg.external_user_id):
        return

    cmd = parse_emu_command(msg.text)
    if cmd is None:
        return

    _logger.info(
        "emu command=%s conversation_type=%s",
        cmd.value, msg.conversation_type.value,
    )

    if cmd == EmuCommand.HELP:
        await send_text_reply(bot, event, TextReply(text=build_help_text()))
    elif cmd == EmuCommand.STATUS:
        await send_text_reply(bot, event, TextReply(text=build_status_text(len(nonebot.get_bots()))))
    elif cmd == EmuCommand.REGISTER:
        await _handle_register(bot, event, msg)
    else:
        await send_text_reply(
            bot, event,
            TextReply(text="未知命令，请使用 /emu help 查看可用命令"),
        )


async def _handle_register(
    bot: Bot, event: MessageEvent, msg: IncomingMessage,
) -> None:
    """Handle /emu register — create a user record from QQ identity."""
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
