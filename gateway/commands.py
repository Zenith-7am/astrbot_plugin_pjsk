"""Pure command parsing and text builders — no NoneBot imports."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
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
    B20 = "b20"
    MY_DIFFICULTY = "my_difficulty"          # "我的ma31"
    GLOBAL_DIFFICULTY = "global_difficulty"  # "难度排行ma31"
    OCR_TRIGGER = "ocr_trigger"              # ".emu" no args (group only)
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedTrigger:
    """Result of parsing a user message as a command trigger."""
    command: EmuCommand
    level: int | None = None  # difficulty level for MY_DIFFICULTY / GLOBAL_DIFFICULTY


# ── Regex patterns ───────────────────────────────────────────────────────────

_STRIP_EMU_PREFIX = re.compile(r"^[.。]emu(?:\s+|$)")
_B20 = re.compile(r"^(?:b20|查b20)$", re.IGNORECASE)
_MY_DIFF = re.compile(r"^我的ma(\d+)$")
_GLOBAL_DIFF = re.compile(r"^难度排行ma(\d+)$")


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


def parse_trigger(text: str, *, is_group: bool) -> ParsedTrigger | None:
    """Parse a non-image text message into a command trigger.

    Private chat: no prefix needed for B20 / difficulty commands.
    Group chat: ``.emu`` or ``。emu`` prefix required.

    Returns None if the message does not match any command.
    """
    text = text.strip()
    if not text:
        return None

    # Group: strip ".emu"/"。emu" prefix
    if is_group:
        if not _STRIP_EMU_PREFIX.match(text):
            return None
        text = _STRIP_EMU_PREFIX.sub("", text).strip()
        # ".emu" / "。emu" with no arguments → OCR trigger
        if not text:
            return ParsedTrigger(EmuCommand.OCR_TRIGGER)

    # B20
    if _B20.match(text):
        return ParsedTrigger(EmuCommand.B20)

    # 我的maXX
    m = _MY_DIFF.match(text)
    if m:
        return ParsedTrigger(EmuCommand.MY_DIFFICULTY, level=int(m.group(1)))

    # 难度排行maXX
    m = _GLOBAL_DIFF.match(text)
    if m:
        return ParsedTrigger(EmuCommand.GLOBAL_DIFFICULTY, level=int(m.group(1)))

    # Legacy /emu commands (private chat only)
    if not is_group:
        legacy = parse_emu_command(text)
        if legacy is not None and legacy != EmuCommand.UNKNOWN:
            return ParsedTrigger(legacy)

    return None


# ── Help text ────────────────────────────────────────────────────────────────

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
