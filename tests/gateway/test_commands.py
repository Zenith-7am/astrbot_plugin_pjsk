"""Tests for gateway.commands — pure functions, no NoneBot imports."""
import pytest
from gateway.commands import (
    EmuCommand,
    parse_emu_command,
    build_help_text,
    build_status_text,
)


class TestParseEmuCommand:
    @pytest.mark.parametrize("text, expected", [
        ("/emu help", EmuCommand.HELP),
        ("/emu status", EmuCommand.STATUS),
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
    ])
    def test_non_emu_text_returns_none(self, text: str) -> None:
        assert parse_emu_command(text) is None


class TestHelpText:
    def test_help_only_lists_implemented_commands(self) -> None:
        text = build_help_text()
        assert "/emu help" in text
        assert "/emu status" in text
        assert "bind" not in text
        assert "b20" not in text
        assert "append" not in text

    def test_help_is_reasonable_length(self) -> None:
        text = build_help_text()
        assert 30 < len(text) < 500


class TestStatusText:
    def test_status_no_secrets(self) -> None:
        text = build_status_text(bot_count=0)
        assert "disconnected" in text
        assert "token" not in text.lower()
        assert "key" not in text.lower()

    def test_status_connected(self) -> None:
        text = build_status_text(bot_count=1)
        assert "connected" in text
