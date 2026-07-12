"""Rating calculation tests — aligned with old emu-bot test_kn_power.py fixtures."""

import pytest
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.rating import calculate_rating
from pjsk_core.domain.scores import ScoreStatus


class TestFcRating:
    """Align with old TestKnPowerFC."""

    def test_fc_exact_100(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.FC,
            accuracy=100.0,
            difficulty=Difficulty.MASTER,
        )
        assert power == 30 * 98  # = 2940

    def test_fc_101(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.FC,
            accuracy=101.0,
            difficulty=Difficulty.MASTER,
        )
        # s = min(3, (101.0 - 100.5) * 6) = min(3, 3) = 3 → 30*(98+3)=3030
        assert abs(power - 30 * 101) < 0.01

    def test_fc_1007(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.FC,
            accuracy=100.7,
            difficulty=Difficulty.MASTER,
        )
        # s = (100.7 - 100.5) * 6 = 1.2 → 30*(98+1.2)=2976
        expected = 30 * (98 + 1.2)
        assert abs(power - expected) < 0.01

    def test_fc_1015(self) -> None:
        """s capped at 3.0 when accuracy ≥ 101.0."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.FC,
            accuracy=101.5,
            difficulty=Difficulty.MASTER,
        )
        assert power == 30 * 101  # = 3030


class TestApRating:
    """Align with old TestKnPowerAP — constant bonus only for MAS/APD/EXP."""

    def test_ap_30_0(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.MASTER,
        )
        # const_bonus=0, 30*101+0+70=3100
        assert power == 30 * 101 + 70

    def test_ap_30_5(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.5",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.MASTER,
        )
        # const_bonus=0.5, round(0.5*20)=10 → 30*101+10+70=3110
        assert power == 30 * 101 + 10 + 70

    def test_ap_with_plus_tag(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.5+",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.MASTER,
        )
        # const_bonus=0.5+0.05=0.55, round(0.55*20)=11 → 3111
        assert power == 30 * 101 + 11 + 70

    def test_ap_with_minus_tag(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.5-",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.MASTER,
        )
        # const_bonus=0.5-0.05=0.45, round(0.45*20)=9 → 3109
        assert power == 30 * 101 + 9 + 70

    def test_ap_non_master_no_const_bonus(self) -> None:
        """HARD AP gets no constant bonus."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.5+",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.HARD,
        )
        assert power == 30 * 101 + 70  # = 3100, no bonus


class TestClearRating:
    """Align with old TestKnPowerEdgeCases."""

    def test_clear_95_percent(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.CLEAR,
            accuracy=95.0,
            difficulty=Difficulty.MASTER,
        )
        # s_clear = (95-90)/7*3 = 2.1428..., Lv*(90+2.1428) ≈ 2764.29
        expected = 30 * (90 + (95.0 - 90.0) / 7.0 * 3.0)
        assert abs(power - expected) < 0.01

    def test_clear_below_90(self) -> None:
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.CLEAR,
            accuracy=80.0,
            difficulty=Difficulty.MASTER,
        )
        assert power == 30 * 90  # s_clear = 0

    def test_clear_1005_plus(self) -> None:
        """≥100.5% CLEAR: s_clear capped at 6.5."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.2",
            status=ScoreStatus.CLEAR,
            accuracy=101.0,
            difficulty=Difficulty.MASTER,
        )
        assert power == 30 * (90 + 6.5)  # = 2895.0

    def test_clear_90_boundary(self) -> None:
        """At exactly 90%: s_clear = 0."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.CLEAR,
            accuracy=90.0,
            difficulty=Difficulty.MASTER,
        )
        assert power == 30 * 90.0  # s = 0

    def test_clear_97_to_100(self) -> None:
        """97% ≤ acc < 100%: s = 3 + (acc-97)/3*2."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.CLEAR,
            accuracy=98.5,
            difficulty=Difficulty.MASTER,
        )
        # s = 3 + (98.5-97)/3*2 = 3 + 1.0 = 4.0
        expected = 30 * (90 + 4.0)
        assert abs(power - expected) < 0.01

    def test_clear_100_to_1005(self) -> None:
        """100% ≤ acc < 100.5%: s = 5 + (acc-100)/0.5."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.CLEAR,
            accuracy=100.25,
            difficulty=Difficulty.MASTER,
        )
        # s = 5 + (100.25-100)/0.5 = 5 + 0.5 = 5.5
        expected = 30 * (90 + 5.5)
        assert abs(power - expected) < 0.01

    def test_clear_100_boundary(self) -> None:
        """At exactly 100%: s = 3 + (100-97)/3*2 = 3 + 2 = 5."""
        power = calculate_rating(
            official_level=30,
            community_constant="30.0",
            status=ScoreStatus.CLEAR,
            accuracy=100.0,
            difficulty=Difficulty.MASTER,
        )
        expected = 30 * (90 + 5.0)
        assert abs(power - expected) < 0.01


class TestRatingEdgeCases:
    def test_invalid_constant_falls_back_to_level(self) -> None:
        """Constant <= 10 treated as invalid, use official_level instead."""
        power = calculate_rating(
            official_level=30,
            community_constant="0.5",  # invalid — too small
            status=ScoreStatus.FC,
            accuracy=100.0,
            difficulty=Difficulty.MASTER,
        )
        assert power == 30 * 98  # = 2940

    def test_ap_expert_gets_const_bonus(self) -> None:
        """EXPERT AP also gets constant bonus."""
        power = calculate_rating(
            official_level=28,
            community_constant="28.3",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.EXPERT,
        )
        # const_bonus=0.3, round(0.3*20)=6 → 28*101+6+70=2904
        assert power == 28 * 101 + 6 + 70

    def test_ap_append_gets_const_bonus(self) -> None:
        """APPEND AP also gets constant bonus."""
        power = calculate_rating(
            official_level=32,
            community_constant="32.0",
            status=ScoreStatus.AP,
            accuracy=101.0,
            difficulty=Difficulty.APPEND,
        )
        assert power == 32 * 101 + 70  # const_bonus=0

    def test_non_numeric_constant_raises(self) -> None:
        """Illegal community_constant must raise ValueError, not return 0.
        New architecture validates inputs early; domain does not swallow
        garbage.  This differs from old bot which returned 0.0."""
        with pytest.raises(ValueError):
            calculate_rating(
                official_level=30,
                community_constant="abc",
                status=ScoreStatus.FC,
                accuracy=100.0,
                difficulty=Difficulty.MASTER,
            )
