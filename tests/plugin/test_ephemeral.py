"""Tests for EphemeralImageBuffer."""

from plugin.ephemeral import EphemeralImageBuffer
from pjsk_core.domain.users import QqNumber


class TestEphemeralImageBuffer:
    def test_put_and_consume_within_window(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"fake_image_data")
        result = buf.consume("onebot", "group:123", qq, within_seconds=15.0)
        assert result == b"fake_image_data"

    def test_consume_removes_entry(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"data")
        buf.consume("onebot", "group:123", qq)
        assert buf.consume("onebot", "group:123", qq) is None

    def test_wrong_group_does_not_match(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"data")
        assert buf.consume("onebot", "group:456", qq) is None

    def test_wrong_user_does_not_match(self) -> None:
        buf = EphemeralImageBuffer()
        qq1 = QqNumber("111")
        qq2 = QqNumber("222")
        buf.put("onebot", "group:123", qq1, b"data")
        assert buf.consume("onebot", "group:123", qq2) is None

    def test_expired_entry_returns_none(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"data")
        # consume with 0s window -> immediate expiry
        result = buf.consume("onebot", "group:123", qq, within_seconds=0.0)
        assert result is None

    def test_second_put_overwrites_for_same_user(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"first")
        buf.put("onebot", "group:123", qq, b"second")
        result = buf.consume("onebot", "group:123", qq)
        assert result == b"second"

    def test_size_limit_rejects_oversized(self) -> None:
        buf = EphemeralImageBuffer(max_size_bytes=10)
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"x" * 11)
        # oversized -> not stored
        assert buf.consume("onebot", "group:123", qq) is None

    async def test_close_clears_all(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"data")
        await buf.close()
        assert buf.consume("onebot", "group:123", qq) is None
