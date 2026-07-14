"""Tests for B20 domain types and pure functions."""

import pytest

from pjsk_core.domain.b20 import (
    B20Entry,
    B20Result,
    RatedScore,
    compute_sp,
    select_b20,
)
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.player_class import calc_player_class
from pjsk_core.domain.scores import Judgements, ScoreStatus


class TestB20Entry:
    def test_is_frozen(self) -> None:
        entry = B20Entry(
            rank=1, song_id=1, song_title="Test",
            difficulty=Difficulty.MASTER, official_level=31,
            community_constant="31.0", status=ScoreStatus.FC,
            accuracy=99.5, rating=33.0,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        )
        with pytest.raises(Exception):
            entry.rank = 2  # type: ignore[misc]


class TestB20Result:
    def test_is_frozen(self) -> None:
        result = B20Result(
            entries=(), sp=0.0,
            player_class=calc_player_class(0.0),
            b20_avg=0.0, fc_bonus=0.0, ap_bonus=0.0,
            append_excluded=True, chart_data_version="v1",
        )
        with pytest.raises(Exception):
            result.sp = 100.0  # type: ignore[misc]


class TestSelectB20:
    def test_excludes_clear(self) -> None:
        scores = [
            RatedScore(chart_id=1, rating=30.0, accuracy=99.0, status=ScoreStatus.FC),
            RatedScore(chart_id=2, rating=28.0, accuracy=98.0, status=ScoreStatus.CLEAR),
        ]
        result = select_b20(scores)
        assert len(result) == 1
        assert result[0].chart_id == 1

    def test_sorts_by_rating_desc(self) -> None:
        scores = [
            RatedScore(chart_id=1, rating=25.0, accuracy=99.0, status=ScoreStatus.FC),
            RatedScore(chart_id=2, rating=35.0, accuracy=99.0, status=ScoreStatus.AP),
            RatedScore(chart_id=3, rating=30.0, accuracy=99.0, status=ScoreStatus.FC),
        ]
        result = select_b20(scores)
        assert result[0].chart_id == 2  # 35.0
        assert result[1].chart_id == 3  # 30.0
        assert result[2].chart_id == 1  # 25.0

    def test_rating_tie_broken_by_chart_id(self) -> None:
        scores = [
            RatedScore(chart_id=5, rating=30.0, accuracy=99.0, status=ScoreStatus.FC),
            RatedScore(chart_id=3, rating=30.0, accuracy=99.0, status=ScoreStatus.FC),
        ]
        result = select_b20(scores)
        assert result[0].chart_id == 3
        assert result[1].chart_id == 5

    def test_returns_at_most_limit(self) -> None:
        scores = [
            RatedScore(chart_id=i, rating=float(30 - i), accuracy=99.0, status=ScoreStatus.FC)
            for i in range(30)
        ]
        result = select_b20(scores, limit=20)
        assert len(result) == 20

    def test_fewer_than_limit_is_valid(self) -> None:
        scores = [
            RatedScore(chart_id=1, rating=30.0, accuracy=99.0, status=ScoreStatus.FC),
        ]
        result = select_b20(scores, limit=20)
        assert len(result) == 1


class TestComputeSp:
    def test_empty_entries_returns_zero(self) -> None:
        sp, b20_avg, fc_bonus, ap_bonus = compute_sp(())
        assert sp == 0.0
        assert b20_avg == 0.0
        assert fc_bonus == 0.0
        assert ap_bonus == 0.0

    def test_single_entry(self) -> None:
        entry = B20Entry(
            rank=1, song_id=1, song_title="Test",
            difficulty=Difficulty.MASTER, official_level=31,
            community_constant="31.0", status=ScoreStatus.FC,
            accuracy=99.5, rating=33.0,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        )
        sp, b20_avg, fc_bonus, ap_bonus = compute_sp((entry,))
        assert b20_avg == 33.0
        assert sp == 33.0
        assert fc_bonus == 0.0
        assert ap_bonus == 0.0

    def test_multiple_entries_average(self) -> None:
        e1 = B20Entry(
            rank=1, song_id=1, song_title="A",
            difficulty=Difficulty.MASTER, official_level=31,
            community_constant="31.0", status=ScoreStatus.FC,
            accuracy=99.5, rating=33.0,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        )
        e2 = B20Entry(
            rank=2, song_id=2, song_title="B",
            difficulty=Difficulty.MASTER, official_level=30,
            community_constant="30.0", status=ScoreStatus.FC,
            accuracy=99.0, rating=29.0,
            judgements=Judgements(perfect=900, great=0, good=0, bad=0, miss=0),
        )
        sp, b20_avg, fc_bonus, ap_bonus = compute_sp((e1, e2))
        assert b20_avg == 31.0
        assert sp == 31.0

    def test_bonuses_are_zero(self) -> None:
        """Full FC/AP bonuses are reserved and always 0.0."""
        entry = B20Entry(
            rank=1, song_id=1, song_title="Test",
            difficulty=Difficulty.MASTER, official_level=31,
            community_constant="31.0", status=ScoreStatus.AP,
            accuracy=101.0, rating=35.0,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        )
        _, _, fc_bonus, ap_bonus = compute_sp((entry,))
        assert fc_bonus == 0.0
        assert ap_bonus == 0.0
