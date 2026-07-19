"""Tests for pjsk_core.domain.scores — status, judgements, attempts, and pure rules."""

from datetime import datetime, timezone

import pytest
from pjsk_core.domain.scores import (
    Judgements,
    ScoreAttempt,
    ScoreStatus,
    calculate_accuracy,
    classify_status,
)
from pjsk_core.domain.users import UserId


class TestScoreStatus:
    def test_three_members(self) -> None:
        members = list(ScoreStatus)
        assert len(members) == 3
        names = {m.name for m in members}
        assert names == {"AP", "FC", "CLEAR"}

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("ap", ScoreStatus.AP),
            ("fc", ScoreStatus.FC),
            ("clear", ScoreStatus.CLEAR),
        ],
    )
    def test_from_string(self, value: str, expected: ScoreStatus) -> None:
        assert ScoreStatus(value) is expected


class TestJudgements:
    def test_all_perfect(self) -> None:
        j = Judgements(perfect=1000, great=0, good=0, bad=0, miss=0)
        assert j.perfect == 1000
        assert j.great == 0

    def test_mixed_judgements(self) -> None:
        j = Judgements(perfect=900, great=80, good=15, bad=3, miss=2)
        assert j.perfect == 900
        assert j.great == 80
        assert j.good == 15
        assert j.bad == 3
        assert j.miss == 2

    def test_all_zeros_is_valid(self) -> None:
        j = Judgements(perfect=0, great=0, good=0, bad=0, miss=0)
        assert j.perfect == 0

    def test_negative_perfect_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=-1, great=0, good=0, bad=0, miss=0)

    def test_negative_great_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=-1, good=0, bad=0, miss=0)

    def test_negative_good_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=0, good=-1, bad=0, miss=0)

    def test_negative_bad_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=0, good=0, bad=-1, miss=0)

    def test_negative_miss_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=0, good=0, bad=0, miss=-1)

    def test_frozen(self) -> None:
        j = Judgements(perfect=1, great=0, good=0, bad=0, miss=0)
        with pytest.raises(Exception):
            j.perfect = 2  # type: ignore[misc]


class TestScoreAttempt:
    def test_valid_attempt(self) -> None:
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=42,
            judgements=Judgements(perfect=1000, great=10, good=0, bad=0, miss=0),
            accuracy=100.5,
            rating=3200.0,
            status=ScoreStatus.FC,
            image_sha256="abc123",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        assert attempt.id is None
        assert attempt.user_id == UserId(1)
        assert attempt.chart_id == 42
        assert attempt.status == ScoreStatus.FC

    def test_with_id(self) -> None:
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=1,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            accuracy=101.0,
            rating=3500.0,
            status=ScoreStatus.AP,
            image_sha256="def456",
            source_gateway="astrbot",
            ocr_run_id=5,
            created_at=now,
        )
        assert attempt.id == 1

    def test_naive_datetime_raises(self) -> None:
        naive = datetime(2026, 7, 12, 12, 0, 0)  # no tzinfo
        with pytest.raises(ValueError):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=50.0,
                rating=100.0,
                status=ScoreStatus.CLEAR,
                image_sha256="ghi789",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=naive,
            )

    def test_frozen(self) -> None:
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            accuracy=100.0,
            rating=3000.0,
            status=ScoreStatus.FC,
            image_sha256="abc",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        with pytest.raises(Exception):
            attempt.accuracy = 99.0  # type: ignore[misc]

    # ── Finite / range guards ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "accuracy",
        [float("nan"), float("inf"), -float("inf")],
        ids=["nan", "+inf", "-inf"],
    )
    def test_non_finite_accuracy_raises(self, accuracy: float) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="accuracy must be finite"):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=accuracy,
                rating=3000.0,
                status=ScoreStatus.CLEAR,
                image_sha256="abc",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=now,
            )

    def test_accuracy_above_101_raises(self) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="accuracy must be between 0 and 101"):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=101.0001,
                rating=3000.0,
                status=ScoreStatus.CLEAR,
                image_sha256="abc",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=now,
            )

    def test_accuracy_101_valid(self) -> None:
        """101.0 (AP) is the maximum valid accuracy."""
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0,
            rating=3500.0,
            status=ScoreStatus.AP,
            image_sha256="abc",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        assert attempt.accuracy == 101.0

    def test_negative_accuracy_raises(self) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="accuracy must be between 0 and 101"):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=-0.1,
                rating=3000.0,
                status=ScoreStatus.CLEAR,
                image_sha256="abc",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=now,
            )

    @pytest.mark.parametrize(
        "rating",
        [float("nan"), float("inf"), -float("inf")],
        ids=["nan", "+inf", "-inf"],
    )
    def test_non_finite_rating_raises(self, rating: float) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="rating must be finite"):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=99.0,
                rating=rating,
                status=ScoreStatus.CLEAR,
                image_sha256="abc",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=now,
            )

    def test_negative_rating_raises(self) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="rating must be non-negative"):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=99.0,
                rating=-1.0,
                status=ScoreStatus.CLEAR,
                image_sha256="abc",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=now,
            )


# ── Accuracy and status rules (aligned with old emu-bot fixtures) ──────


class TestCalculateAccuracy:
    """Align with old emu-bot test_accuracy.py fixtures."""

    def test_all_perfect(self) -> None:
        j = Judgements(perfect=1200, great=0, good=0, bad=0, miss=0)
        assert calculate_accuracy(j) == 101.0

    def test_mixed(self) -> None:
        j = Judgements(perfect=1000, great=200, good=50, bad=10, miss=5)
        acc = calculate_accuracy(j)
        # (P + G×0.75 + Good×0.5) / N × 101, capped at 101
        expected = min(101.0, (1000 + 200 * 0.75 + 50 * 0.5) / 1265 * 101)
        assert abs(acc - expected) < 0.1

    def test_all_miss(self) -> None:
        j = Judgements(perfect=0, great=0, good=0, bad=0, miss=1200)
        assert calculate_accuracy(j) == 0.0

    def test_empty(self) -> None:
        j = Judgements(perfect=0, great=0, good=0, bad=0, miss=0)
        assert calculate_accuracy(j) == 0.0

    def test_cap_at_101(self) -> None:
        j = Judgements(perfect=1300, great=0, good=0, bad=0, miss=0)
        assert calculate_accuracy(j) == 101.0

    def test_fc_with_great(self) -> None:
        """FC allows GREAT; accuracy uses 75% weight, not forced to 101."""
        j = Judgements(perfect=1100, great=100, good=0, bad=0, miss=0)
        acc = calculate_accuracy(j)
        expected = (1100 + 100 * 0.75) / 1200 * 101
        assert abs(acc - expected) < 0.01

    def test_clear_with_good(self) -> None:
        """GOOD at 50% weight; not AP even if perfect is high."""
        j = Judgements(perfect=1000, great=0, good=200, bad=0, miss=0)
        acc = calculate_accuracy(j)
        expected = (1000 + 200 * 0.5) / 1200 * 101
        assert abs(acc - expected) < 0.01


class TestClassifyStatus:
    def test_ap(self) -> None:
        j = Judgements(perfect=1000, great=0, good=0, bad=0, miss=0)
        assert classify_status(j) is ScoreStatus.AP

    def test_fc_with_great(self) -> None:
        j = Judgements(perfect=990, great=10, good=0, bad=0, miss=0)
        assert classify_status(j) is ScoreStatus.FC

    def test_fc_no_perfect(self) -> None:
        """0 perfect + some great + no combo breaks — still FC."""
        j = Judgements(perfect=0, great=100, good=0, bad=0, miss=0)
        assert classify_status(j) is ScoreStatus.FC

    def test_clear_with_good(self) -> None:
        j = Judgements(perfect=900, great=0, good=1, bad=0, miss=0)
        assert classify_status(j) is ScoreStatus.CLEAR

    def test_clear_with_bad(self) -> None:
        j = Judgements(perfect=900, great=0, good=0, bad=1, miss=0)
        assert classify_status(j) is ScoreStatus.CLEAR

    def test_clear_with_miss(self) -> None:
        j = Judgements(perfect=900, great=0, good=0, bad=0, miss=1)
        assert classify_status(j) is ScoreStatus.CLEAR

    def test_empty_is_clear(self) -> None:
        """All-zero judgements — not a real play, classify as CLEAR."""
        j = Judgements(perfect=0, great=0, good=0, bad=0, miss=0)
        assert classify_status(j) is ScoreStatus.CLEAR
