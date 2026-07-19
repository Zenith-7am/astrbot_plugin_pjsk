"""Tests for gateway.commands — pure functions, no NoneBot imports."""
import pytest
from gateway.commands import (
    EmuCommand,
    parse_emu_command,
    parse_trigger,
    build_help_text,
    build_status_text,
)


class TestParseEmuCommand:
    @pytest.mark.parametrize("text, expected", [
        ("/emu help", EmuCommand.HELP),
        ("/emu status", EmuCommand.STATUS),
        ("/emu register", EmuCommand.REGISTER),
        ("/emu b20", EmuCommand.UNKNOWN),
        ("/emu xyz", EmuCommand.UNKNOWN),
        ("/emu", EmuCommand.UNKNOWN),
        ("/emu  ", EmuCommand.UNKNOWN),
    ])
    def test_valid_emu_commands(self, text: str, expected: object) -> None:
        assert parse_emu_command(text) is expected

    @pytest.mark.parametrize("text", [
        "今天天气真好",
        "你好",
        "b20",
        "查b20",
        "帮助",
        "/pjsk b20",
        "",
        "emu b20",
        "/",
        "/emulator",
        "/emulator",  # prefix collision: not /emu
    ])
    def test_non_emu_text_returns_none(self, text: str) -> None:
        assert parse_emu_command(text) is None


class TestHelpText:
    def test_help_lists_implemented_commands(self) -> None:
        text = build_help_text()
        assert "帮助" in text or "/emu help" in text
        assert "状态" in text or "/emu status" in text
        assert "注册" in text
        assert "b20" in text

    def test_help_is_reasonable_length(self) -> None:
        text = build_help_text()
        assert 50 < len(text) < 900


class TestStatusText:
    def test_status_no_secrets(self) -> None:
        text = build_status_text(bot_count=0)
        assert "disconnected" in text
        assert "token" not in text.lower()
        assert "key" not in text.lower()

    def test_status_connected(self) -> None:
        text = build_status_text(bot_count=1)
        assert "connected" in text


# ── parse_trigger (new command system) ───────────────────────────────────────


class TestParseTriggerPrivate:
    """Private chat: no prefix needed."""

    @pytest.mark.parametrize("text, cmd", [
        ("b20", EmuCommand.B20),
        ("查b20", EmuCommand.B20),
        ("B20", EmuCommand.B20),
    ])
    def test_b20_variants(self, text: str, cmd: EmuCommand) -> None:
        result = parse_trigger(text, is_group=False)
        assert result is not None
        assert result.command == cmd

    @pytest.mark.parametrize("text, level", [
        ("我的ma31", 31),
        ("我的ma26", 26),
        ("我的ma37", 37),
    ])
    def test_my_difficulty(self, text: str, level: int) -> None:
        result = parse_trigger(text, is_group=False)
        assert result is not None
        assert result.command == EmuCommand.MY_DIFFICULTY
        assert result.level == level

    @pytest.mark.parametrize("text, level", [
        ("难度排行ma31", 31),
        ("难度排行ma30", 30),
    ])
    def test_global_difficulty(self, text: str, level: int) -> None:
        result = parse_trigger(text, is_group=False)
        assert result is not None
        assert result.command == EmuCommand.GLOBAL_DIFFICULTY
        assert result.level == level

    def test_legacy_emu_register(self) -> None:
        result = parse_trigger("/emu register", is_group=False)
        assert result is not None
        assert result.command == EmuCommand.REGISTER

    def test_legacy_emu_help(self) -> None:
        result = parse_trigger("/emu help", is_group=False)
        assert result is not None
        assert result.command == EmuCommand.HELP

    @pytest.mark.parametrize("text", [
        "hello",
        "b200",
        "我的ma",
        "难度排行",
        "",
        "b20x",
    ])
    def test_non_matching_returns_none(self, text: str) -> None:
        assert parse_trigger(text, is_group=False) is None



    # ── Register (new bare command) ──────────────────────────────────────

    @pytest.mark.parametrize("text", [
        "register",
        "注册",
        "reg",
    ])
    def test_register_bare(self, text: str) -> None:
        result = parse_trigger(text, is_group=False)
        assert result is not None
        assert result.command == EmuCommand.REGISTER

    def test_register_via_dot_emu_private(self) -> None:
        result = parse_trigger(".emu register", is_group=False)
        assert result is not None
        assert result.command == EmuCommand.REGISTER

    def test_register_via_dot_emu_group(self) -> None:
        result = parse_trigger(".emu register", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.REGISTER

    def test_register_via_slash_emu_with_args(self) -> None:
        result = parse_trigger("/emu register my_game_id", is_group=False)
        assert result is not None
        assert result.command == EmuCommand.REGISTER

class TestParseTriggerGroup:
    """Group chat: .emu / 。emu prefix required."""

    def test_emu_no_args_ocr_trigger(self) -> None:
        result = parse_trigger(".emu", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.OCR_TRIGGER

    def test_chinese_period_ocr_trigger(self) -> None:
        result = parse_trigger("。emu", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.OCR_TRIGGER

    def test_emu_with_trailing_space(self) -> None:
        result = parse_trigger(".emu   ", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.OCR_TRIGGER

    def test_emu_b20(self) -> None:
        result = parse_trigger(".emu b20", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.B20

    def test_chinese_period_b20(self) -> None:
        result = parse_trigger("。emu b20", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.B20

    def test_emu_my_difficulty(self) -> None:
        result = parse_trigger(".emu 我的ma31", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.MY_DIFFICULTY
        assert result.level == 31

    def test_emu_global_difficulty(self) -> None:
        result = parse_trigger(".emu 难度排行ma30", is_group=True)
        assert result is not None
        assert result.command == EmuCommand.GLOBAL_DIFFICULTY
        assert result.level == 30

    @pytest.mark.parametrize("text", [
        "hello",
        "",
    ])
    def test_no_prefix_rejected(self, text: str) -> None:
        """Group: non-command text returns None (filtering by .emu prefix
        is done at the trigger-rule level, NOT in parse_trigger)."""
        assert parse_trigger(text, is_group=True) is None

    def test_emu_prefix_but_garbage(self) -> None:
        """'.emu xyz' should not match any known command."""
        result = parse_trigger(".emu xyz", is_group=True)
        # Does not match B20, MY_DIFF, GLOBAL_DIFF, or legacy /emu
        assert result is None


class TestParseTriggerAppend:
    """append on/off/status commands — bare (private) and .emu prefixed."""

    @pytest.mark.parametrize("text, cmd", [
        ("append on", EmuCommand.APPEND_ON),
        ("append off", EmuCommand.APPEND_OFF),
        ("append status", EmuCommand.APPEND_STATUS),
        ("APPEND ON", EmuCommand.APPEND_ON),
        ("APPEND OFF", EmuCommand.APPEND_OFF),
    ])
    def test_append_bare_private(self, text: str, cmd: EmuCommand) -> None:
        result = parse_trigger(text, is_group=False)
        assert result is not None
        assert result.command == cmd

    @pytest.mark.parametrize("text, cmd", [
        (".emu append on", EmuCommand.APPEND_ON),
        (".emu append off", EmuCommand.APPEND_OFF),
        (".emu append status", EmuCommand.APPEND_STATUS),
        ("。emu append on", EmuCommand.APPEND_ON),
    ])
    def test_append_with_emu_prefix_group(self, text: str, cmd: EmuCommand) -> None:
        result = parse_trigger(text, is_group=True)
        assert result is not None
        assert result.command == cmd

    def test_append_with_emu_prefix_private(self) -> None:
        result = parse_trigger(".emu append on", is_group=False)
        assert result is not None
        assert result.command == EmuCommand.APPEND_ON

    @pytest.mark.parametrize("text", [
        "append",
        "append enable",
        "append xyz",
        "appendon",
    ])
    def test_invalid_append_rejected(self, text: str) -> None:
        assert parse_trigger(text, is_group=False) is None
