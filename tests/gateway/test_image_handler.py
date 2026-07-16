"""Tests for image_handler pure functions (no NoneBot needed)."""
from gateway.matchers.image_handler import (
    _validate_image,
    _format_readonly_result,
    _format_candidates_text,
)


# ── Image validation ─────────────────────────────────────────────────────────


class TestValidateImage:
    def test_valid_jpeg_passes(self) -> None:
        data = b"\xff\xd8\xff" + b"\x00" * 200
        assert _validate_image(data) is None

    def test_valid_png_passes(self) -> None:
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        assert _validate_image(data) is None

    def test_too_small_rejected(self) -> None:
        data = b"\xff\xd8\xff\x00\x00\x00\x00"  # 7 bytes
        assert _validate_image(data) is not None

    def test_too_small_for_screenshot_rejected(self) -> None:
        data = b"\xff\xd8\xff" + b"\x00" * 50  # valid JPEG but < 100 bytes
        assert _validate_image(data) is not None

    def test_too_large_rejected(self) -> None:
        # Create a fake large image
        data = b"\xff\xd8\xff" + b"\x00" * (10 * 1024 * 1024 + 1)
        assert _validate_image(data) is not None

    def test_unknown_format_rejected(self) -> None:
        data = b"\x00\x01\x02\x03\x04\x05\x06\x07" + b"\x00" * 200
        assert _validate_image(data) is not None

    def test_jpeg_at_max_size_passes(self) -> None:
        # At exactly max size
        size = 10 * 1024 * 1024
        data = b"\xff\xd8\xff" + b"\x00" * (size - 3)
        assert _validate_image(data) is None


# ── Result formatting ────────────────────────────────────────────────────────


class _FakeObservation:
    song_title = "Test Song"
    difficulty = None  # set per test
    displayed_level = 31
    judgements = None  # set per test


class _FakeJudgements:
    perfect = 1000
    great = 100
    good = 10
    bad = 5
    miss = 2


class _FakeChart:
    community_constant = "31.5"


class _FakePrimary:
    chart = _FakeChart()


class _FakeValidated:
    observation = _FakeObservation()
    primary = _FakePrimary()


class _FakeAttempt:
    status = None  # set per test
    accuracy = 100.5
    rating = 3150.0


class _FakeOutcome:
    decision = None  # set per test


class _FakeRecognizeResult:
    outcome = _FakeOutcome()
    validated = _FakeValidated()
    candidates_for_user = ()
    score_attempt = _FakeAttempt()


class TestFormatReadonlyResult:
    def setup_method(self) -> None:
        from pjsk_core.domain.charts import Difficulty
        from pjsk_core.application.vision_race import VisionRaceDecision
        _FakeObservation.difficulty = Difficulty.MASTER
        _FakeObservation.judgements = _FakeJudgements()
        from pjsk_core.domain.scores import ScoreStatus
        _FakeAttempt.status = ScoreStatus.FC
        _FakeOutcome.decision = VisionRaceDecision.CONSENSUS

    def test_shows_song_and_difficulty(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "Test Song" in text
        assert "MASTER 31" in text

    def test_shows_judgements(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "PERFECT：1000" in text
        assert "GREAT：100" in text
        assert "GOOD：10" in text
        assert "BAD：5" in text
        assert "MISS：2" in text

    def test_shows_acc_and_rating(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "ACC：100.5000%" in text
        assert "Rating：3150.00" in text

    def test_shows_status(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "状态：FC" in text

    def test_shows_consensus_label(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "多模型共识" in text

    def test_shows_degraded_single_label(self) -> None:
        from pjsk_core.application.vision_race import VisionRaceDecision
        _FakeOutcome.decision = VisionRaceDecision.DEGRADED_SINGLE
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "单模型识别" in text

    def test_no_secrets_in_output(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        assert "token" not in text.lower()
        assert "key" not in text.lower()

    def test_no_qq_in_output(self) -> None:
        result = _FakeRecognizeResult()
        text = _format_readonly_result(result)
        # No QQ-like patterns
        assert "user_id" not in text.lower()


class TestFormatCandidatesText:
    def test_shows_candidate_count(self) -> None:
        from pjsk_core.domain.charts import Difficulty
        from pjsk_core.application.vision_race import VisionRaceDecision

        class _FakeCandidate:
            observation = _FakeObservation()
            model_support = 2
            matched_chart_id = 42
        _FakeObservation.difficulty = Difficulty.MASTER
        _FakeObservation.judgements = _FakeJudgements()
        _FakeOutcome.decision = VisionRaceDecision.DISAGREEMENT

        result = _FakeRecognizeResult()
        result.candidates_for_user = (_FakeCandidate(), _FakeCandidate())

        text = _format_candidates_text(result)
        assert "[1]" in text
        assert "[2]" in text
        assert "多模型识别不一致" in text

    def test_no_candidates_shows_retry(self) -> None:
        result = _FakeRecognizeResult()
        result.candidates_for_user = ()
        text = _format_candidates_text(result)
        assert "重新发送" in text
