"""Pure command parsing and text builders — no NoneBot imports."""
from __future__ import annotations

import os
from enum import Enum

GATEWAY_VERSION = "0.2.0-dev"


def qq_allowed(external_user_id: str) -> bool:
    """Check whether a QQ number is allowed to interact with the bot.

    If TEST_QQ_ALLOWLIST is set, only listed QQ numbers receive replies.
    If unset (production), all users are served.
    """
    allowed = os.environ.get("TEST_QQ_ALLOWLIST", "")
    if not allowed:
        return True
    return external_user_id in allowed.split(",")


class EmuCommand(Enum):
    HELP = "help"
    STATUS = "status"
    REGISTER = "register"
    UNKNOWN = "unknown"


def parse_emu_command(text: str) -> EmuCommand | None:
    """Parse '/emu <subcommand>'. Returns None if not an /emu command.

    Requires '/emu' followed by end-of-string or whitespace —
    '/emulator' returns None (prefix collision defence).
    """
    stripped = text.strip()
    if not stripped.startswith("/emu"):
        return None
    # "/emu" with nothing after, or "/emu<non-space>" like "/emulator" → None
    if len(stripped) == 4:
        return EmuCommand.UNKNOWN
    if stripped[4] != " ":
        return None  # "/emulator" or "/emuxyz"
    arg = stripped[5:].strip()
    if arg in ("help",):
        return EmuCommand.HELP
    if arg in ("status",):
        return EmuCommand.STATUS
    if arg in ("register",):
        return EmuCommand.REGISTER
    return EmuCommand.UNKNOWN


_HELP = (
    "PJSK Emu Bot\n"
    "\n"
    "/emu help              显示此帮助\n"
    "/emu status            查看运行状态\n"
    "/emu register          注册账号\n"
)


def build_help_text() -> str:
    return _HELP


def build_status_text(bot_count: int) -> str:
    status = "connected" if bot_count > 0 else "disconnected"
    return f"PJSK Emu Bot {GATEWAY_VERSION}\nOneBot: {status}"
