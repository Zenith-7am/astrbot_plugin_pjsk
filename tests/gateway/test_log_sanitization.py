"""Tests that sensitive data is not leaked via third-party loggers."""
import logging


class TestLoggerLevels:
    """Verify that sanitize_third_party_loggers() sets correct levels."""

    @classmethod
    def setup_class(cls) -> None:
        from gateway.log_config import sanitize_third_party_loggers
        sanitize_third_party_loggers()

    def test_httpx_logger_is_warning(self) -> None:
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_httpcore_logger_is_warning(self) -> None:
        assert logging.getLogger("httpcore").level == logging.WARNING

    def test_nonebot_adapters_logger_is_warning(self) -> None:
        assert logging.getLogger("nonebot.adapters").level == logging.WARNING


class TestReplyTextNoSecrets:
    """Verify that reply text formatting never leaks credentials or PII."""

    def test_format_readonly_result_no_key(self) -> None:
        from gateway.matchers.image_handler import _format_readonly_result
        from pjsk_core.application.vision_race import VisionRaceDecision

        class _FakeObs:
            song_title = "Test"
            difficulty = None  # set below
            displayed_level = 30
            judgements = None  # set below

        class _FakeJudge:
            perfect = 1000
            great = 100
            good = 0
            bad = 0
            miss = 0

        class _FakeChart:
            community_constant = "30.0"

        class _FakePrimary:
            chart = _FakeChart()

        class _FakeValidated:
            observation = _FakeObs()
            primary = _FakePrimary()

        class _FakeAttempt:
            status = None
            accuracy = 99.5
            rating = 3000.0

        class _FakeOutcome:
            decision = VisionRaceDecision.CONSENSUS

        class _FakeResult:
            outcome = _FakeOutcome()
            validated = _FakeValidated()
            score_attempt = _FakeAttempt()

        from pjsk_core.domain.charts import Difficulty
        from pjsk_core.domain.scores import ScoreStatus
        _FakeObs.difficulty = Difficulty.MASTER
        _FakeObs.judgements = _FakeJudge()
        _FakeAttempt.status = ScoreStatus.FC

        text = _format_readonly_result(_FakeResult())
        for secret in ("key", "token", "api", "secret", "password", "3366463190"):
            assert secret not in text.lower(), f"Leaked '{secret}' in: {text[:80]}"
