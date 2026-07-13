"""Tests for EphemeralImageBuffer."""

from pjsk_emubot.ephemeral import EphemeralImageBuffer
from pjsk_core.domain.users import QqNumber


class FakeClock:
    """Deterministic clock for TTL tests."""
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


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
        clock = FakeClock(0.0)
        buf = EphemeralImageBuffer(clock=clock)
        qq = QqNumber("123456")
        buf.put("onebot", "group:123", qq, b"data")
        # Advance past TTL — entry is now expired
        clock.advance(0.1)
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


class TestEphemeralImageBufferArm:
    """Tests for arm/consume_arm — mention-window state (Commit 1 R4)."""

    def test_arm_and_consume_within_window(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.arm("onebot", "group:123", qq)
        assert buf.consume_arm("onebot", "group:123", qq, within_seconds=15.0) is True

    def test_consume_arm_is_one_shot(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.arm("onebot", "group:123", qq)
        buf.consume_arm("onebot", "group:123", qq)
        assert buf.consume_arm("onebot", "group:123", qq) is False

    def test_arm_without_prior_arm_returns_false(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        assert buf.consume_arm("onebot", "group:123", qq) is False

    def test_arm_expires_after_ttl(self) -> None:
        clock = FakeClock(0.0)
        buf = EphemeralImageBuffer(clock=clock)
        qq = QqNumber("123456")
        buf.arm("onebot", "group:123", qq)
        clock.advance(16.0)
        assert buf.consume_arm("onebot", "group:123", qq, within_seconds=15.0) is False

    def test_arm_different_user_does_not_match(self) -> None:
        buf = EphemeralImageBuffer()
        qq1 = QqNumber("111")
        qq2 = QqNumber("222")
        buf.arm("onebot", "group:123", qq1)
        assert buf.consume_arm("onebot", "group:123", qq2) is False

    def test_arm_different_group_does_not_match(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.arm("onebot", "group:123", qq)
        assert buf.consume_arm("onebot", "group:456", qq) is False

    def test_arm_different_platform_does_not_match(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.arm("onebot", "group:123", qq)
        assert buf.consume_arm("qq_official", "group:123", qq) is False

    async def test_close_clears_arms(self) -> None:
        buf = EphemeralImageBuffer()
        qq = QqNumber("123456")
        buf.arm("onebot", "group:123", qq)
        await buf.close()
        assert buf.consume_arm("onebot", "group:123", qq) is False
