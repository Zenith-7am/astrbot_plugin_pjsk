"""Tests for pjsk_core.domain.scores — status, judgements, and attempts."""

from datetime import datetime, timezone

import pytest
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
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
