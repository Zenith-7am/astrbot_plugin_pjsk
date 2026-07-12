"""B20 selection tests — top N FC/AP scores by rating, chart_id tiebreaker."""

from pjsk_core.domain.b20 import RatedScore, select_b20
from pjsk_core.domain.scores import ScoreStatus


def _fc(chart_id: int, rating: float) -> RatedScore:
    return RatedScore(chart_id=chart_id, rating=rating, accuracy=100.0, status=ScoreStatus.FC)


def _ap(chart_id: int, rating: float) -> RatedScore:
    return RatedScore(chart_id=chart_id, rating=rating, accuracy=101.0, status=ScoreStatus.AP)


class TestSelectB20:
    def test_top_20_from_30(self) -> None:
        scores = [_fc(i, float(100 - i)) for i in range(1, 31)]
        result = select_b20(scores)
        assert len(result) == 20
        assert result[0].chart_id == 1
        assert result[-1].chart_id == 20

    def test_clear_excluded(self) -> None:
        scores = [
            _ap(1, 3500),
            RatedScore(2, 3400, 100.0, ScoreStatus.CLEAR),
            _fc(3, 3300),
        ]
        result = select_b20(scores)
        assert len(result) == 2
        assert all(s.status != ScoreStatus.CLEAR for s in result)

    def test_tiebreaker_by_chart_id(self) -> None:
        scores = [
            _fc(2, 3000),
            _fc(1, 3000),
        ]
        result = select_b20(scores)
        assert result[0].chart_id == 1
        assert result[1].chart_id == 2

    def test_fewer_than_20(self) -> None:
        scores = [_fc(i, 100.0) for i in range(1, 6)]
        result = select_b20(scores)
        assert len(result) == 5

    def test_empty(self) -> None:
        assert select_b20([]) == []

    def test_ap_and_fc_both_eligible(self) -> None:
        scores = [
            _fc(1, 3100),
            _ap(2, 3200),
            _fc(3, 3000),
        ]
        result = select_b20(scores)
        assert len(result) == 3
        assert result[0].status == ScoreStatus.AP

    def test_rating_descending_order(self) -> None:
        scores = [_fc(i, float(i * 100)) for i in [3, 1, 5, 2, 4]]
        result = select_b20(scores)
        ratings = [s.rating for s in result]
        assert ratings == [500, 400, 300, 200, 100]
