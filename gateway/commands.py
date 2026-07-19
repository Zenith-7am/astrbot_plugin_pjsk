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
    APPEND_ON = "append_on"
    APPEND_OFF = "append_off"
    APPEND_STATUS = "append_status"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedTrigger:
    """Result of parsing a user message as a command trigger."""
    command: EmuCommand
    level: int | None = None  # difficulty level for MY_DIFFICULTY / GLOBAL_DIFFICULTY
    difficulty: str | None = None  # "master"/"expert"/"append"/"hard"/"normal"/"easy"


# ── Regex patterns ───────────────────────────────────────────────────────────

_STRIP_EMU_PREFIX = re.compile(r"^[.。]emu(?:\s+|$)")
_B20 = re.compile(r"^(?:b20|查b20)$", re.IGNORECASE)
_REGISTER = re.compile(r"^(?:reg(?:ister)?|注册)$", re.IGNORECASE)
# Capture: <prefix><abbrev><level>
# e.g. "我的ma31" → difficulty="ma", level=31
# e.g. "我的ex28" → difficulty="ex", level=28
_DIFF_CAPTURE = re.compile(r"^(?:我的|难度排行)(ma|ex|apd|hd|nm|ez)(\d+)$")
_APPEND_CMD = re.compile(r"^append\s+(on|off|status)$", re.IGNORECASE)

# Abbreviation → Difficulty enum value
_DIFF_ABBREV_MAP: dict[str, str] = {
    "ez": "easy", "nm": "normal", "hd": "hard",
    "ex": "expert", "ma": "master", "apd": "append",
}


def _strip_emu_prefix(text: str) -> str | None:
    """If *text* starts with .emu / 。emu, return the remainder. Else None."""
    m = _STRIP_EMU_PREFIX.match(text)
    if not m:
        return None
    return _STRIP_EMU_PREFIX.sub("", text).strip()


def parse_emu_command(text: str) -> EmuCommand | None:
    """Parse '/emu <subcommand>'.  Also accepts '.emu <subcommand>' for
    backward compatibility with users who type the dot prefix.

    Requires '/emu' or '.emu' followed by end-of-string or whitespace —
    '/emulator' and '.emulator' return None (prefix collision defence).
    """
    stripped = text.strip()

    # Accept both /emu and .emu as prefix
    if stripped.startswith("/emu"):
        body = stripped[4:]
    elif stripped.startswith(".emu") or stripped.startswith("。emu"):
        body = stripped[4:]
    else:
        return None

    # "/emu" / ".emu" with nothing after → UNKNOWN (catch by OCR trigger)
    if not body:
        return EmuCommand.UNKNOWN
    # "/emulator" or "/emuxyz" → not our command
    if body[0] != " ":
        return None
    arg = body[1:].strip()
    if arg in ("help",):
        return EmuCommand.HELP
    if arg in ("status",):
        return EmuCommand.STATUS
    if arg == "register" or arg.startswith("register "):
        return EmuCommand.REGISTER
    return EmuCommand.UNKNOWN


def parse_trigger(text: str, *, is_group: bool) -> ParsedTrigger | None:
    """Parse a non-image text message into a command trigger.

    **Private chat**: bare commands (b20, register, 注册 …) or
    ``.emu <cmd>`` / ``/emu <cmd>`` prefixes.

    **Group chat**: ``.emu`` / ``。emu`` prefix required; after stripping,
    bare commands (b20, register, 注册, 我的maXX, 难度排行maXX) are recognised.

    Returns None if the message does not match any command.
    """
    text = text.strip()
    if not text:
        return None

    # Strip ".emu"/"。emu" prefix in BOTH private and group
    remainder = _strip_emu_prefix(text)
    if remainder is not None:
        text = remainder
        # ".emu" / "。emu" with no arguments → OCR trigger
        if not text:
            return ParsedTrigger(EmuCommand.OCR_TRIGGER)

    # ── Bare commands (work everywhere) ──────────────────────────────────

    if _B20.match(text):
        return ParsedTrigger(EmuCommand.B20)

    if _REGISTER.match(text):
        return ParsedTrigger(EmuCommand.REGISTER)

    m = _DIFF_CAPTURE.match(text)
    if m:
        abbrev, level_str = m.group(1), m.group(2)
        diff = _DIFF_ABBREV_MAP.get(abbrev)
        if diff is None:
            return None
        is_personal = text.startswith("我的")
        cmd = EmuCommand.MY_DIFFICULTY if is_personal else EmuCommand.GLOBAL_DIFFICULTY
        return ParsedTrigger(cmd, level=int(level_str), difficulty=diff)

    m = _APPEND_CMD.match(text)
    if m:
        sub = m.group(1).lower()
        if sub == "on":
            return ParsedTrigger(EmuCommand.APPEND_ON)
        elif sub == "off":
            return ParsedTrigger(EmuCommand.APPEND_OFF)
        else:
            return ParsedTrigger(EmuCommand.APPEND_STATUS)

    if text in ("help", "帮助"):
        return ParsedTrigger(EmuCommand.HELP)
    if text in ("status", "状态"):
        return ParsedTrigger(EmuCommand.STATUS)

    # ── Legacy /emu and .emu commands ─────────────────────────────────────
    legacy = parse_emu_command(text)
    if legacy is not None and legacy != EmuCommand.UNKNOWN:
        return ParsedTrigger(legacy)

    return None


# ── Help text / image ───────────────────────────────────────────────────────

_HELP = (
    "PJSK Emu Bot\n"
    "\n"
    "私聊命令（直接发送）:\n"
    "  注册 / register         注册账号\n"
    "  b20                     查询 B20 排行\n"
    "  我的ma31                 个人 MA 31 排行\n"
    "  难度排行ex28              全局 EX 28 排行\n"
    "\n"
    "难度排行缩写: ez(简单) nm(普通) hd(困难)\n"
    "              ex(专家) ma(大师) apd(附加)\n"
    "\n"
    "群聊命令（.emu 前缀）:\n"
    "  .emu                    识别刚才发的截图\n"
    "  .emu register           注册账号\n"
    "  .emu b20                查询 B20 排行\n"
    "  .emu 我的ma31            个人 MA 31 排行\n"
    "  .emu 难度排行ex28         全局 EX 28 排行\n"
    "\n"
    "帮助 /help /emu help\n"
    "状态 /emu status"
)

_HELP_PNG: bytes | None = None
_HELP_PNG_PATHS: list[str] = []


def build_help_text() -> str:
    return _HELP


def load_help_png() -> bytes | None:
    """Return the pre-rendered help menu PNG bytes (cached in memory).

    Searches *project_root*/assets/help_menu.png and
    /opt/pjsk-astrbot/shared/assets/help_menu.png.
    """
    global _HELP_PNG

    if _HELP_PNG is not None:
        return _HELP_PNG

    if not _HELP_PNG_PATHS:
        # Delayed init so callers don't pay the import-time stat cost.
        _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _HELP_PNG_PATHS.extend([
            os.path.join(_project_root, "assets", "help_menu.png"),
            "/opt/pjsk-astrbot/shared/assets/help_menu.png",
        ])

    for p in _HELP_PNG_PATHS:
        if os.path.exists(p):
            with open(p, "rb") as f:
                _HELP_PNG = f.read()
            return _HELP_PNG

    return None


def build_status_text(bot_count: int) -> str:
    status = "connected" if bot_count > 0 else "disconnected"
    return f"PJSK Emu Bot {GATEWAY_VERSION}\nOneBot: {status}"
