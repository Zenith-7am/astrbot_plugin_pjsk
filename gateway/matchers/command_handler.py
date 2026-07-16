"""NoneBot matcher for /emu — imports pure functions from gateway.commands."""
from __future__ import annotations

import logging

import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from pjsk_core.application.replies import TextReply
from gateway.commands import EmuCommand, parse_emu_command, build_help_text, build_status_text
from gateway.adapters.event_mapper import map_event
from gateway.adapters.reply_sender import send_text_reply

_logger = logging.getLogger(__name__)

emu_cmd = on_command("emu", priority=20, block=True)


@emu_cmd.handle()  # type: ignore[misc]
async def _emu(bot: Bot, event: MessageEvent) -> None:
    msg = map_event(event)
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
    else:
        await send_text_reply(
            bot, event,
            TextReply(text="未知命令，请使用 /emu help 查看可用命令"),
        )
