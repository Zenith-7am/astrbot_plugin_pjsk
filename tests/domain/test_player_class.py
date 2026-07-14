"""Tests for pjsk_core.domain.player_class — PlayerClass value object and calc_player_class."""

import pytest
from pjsk_core.domain.player_class import PlayerClass, calc_player_class


class TestPlayerClassDataclass:
    def test_field_access(self) -> None:
        pc = PlayerClass(name="Test", icon="T", stars=5, fallback_color="red")
        assert pc.name == "Test"
        assert pc.icon == "T"
        assert pc.stars == 5
        assert pc.fallback_color == "red"

    def test_is_frozen(self) -> None:
        pc = PlayerClass(name="Test", icon="T", stars=5, fallback_color="red")
        with pytest.raises(Exception):
            pc.name = "Changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = PlayerClass(name="Test", icon="T", stars=5, fallback_color="red")
        b = PlayerClass(name="Test", icon="T", stars=5, fallback_color="red")
        assert a == b

    def test_inequality(self) -> None:
        a = PlayerClass(name="A", icon="T", stars=5, fallback_color="red")
        b = PlayerClass(name="B", icon="T", stars=5, fallback_color="red")
        assert a != b

    def test_hashable(self) -> None:
        a = PlayerClass(name="Test", icon="T", stars=5, fallback_color="red")
        b = PlayerClass(name="Test", icon="T", stars=5, fallback_color="red")
        assert hash(a) == hash(b)


class TestCalcPlayerClass:
    def test_returns_player_class(self) -> None:
        pc = calc_player_class(3000)
        assert isinstance(pc, PlayerClass)

    # ── Sekai Master (≥ 3939) ──────────────────────────────────────────

    def test_sekai_master_threshold(self) -> None:
        pc = calc_player_class(3939)
        assert pc.name == "SEKAI MASTER"
        assert pc.icon == "🌐"
        assert pc.stars == 10
        assert pc.fallback_color == "blue"

    def test_sekai_master_above_threshold(self) -> None:
        pc = calc_player_class(5000)
        assert pc.name == "SEKAI MASTER"
        assert pc.stars == 10

    # ── Grand Master (3400–3938) ───────────────────────────────────────

    def test_grand_master_lower_boundary(self) -> None:
        pc = calc_player_class(3400)
        assert pc.name == "Grand Master"
        assert pc.icon == "👑"
        assert pc.stars == 1
        assert pc.fallback_color == "purple"

    def test_grand_master_mid_star(self) -> None:
        pc = calc_player_class(3450)
        assert pc.name == "Grand Master"
        assert pc.stars == 2

    def test_grand_master_upper_boundary(self) -> None:
        pc = calc_player_class(3938)
        assert pc.name == "Grand Master"
        assert pc.stars == 9

    def test_grand_master_max_stars_capped(self) -> None:
        pc = calc_player_class(3900)
        assert pc.name == "Grand Master"
        assert pc.stars == 9

    def test_below_grand_master_is_master(self) -> None:
        pc = calc_player_class(3399)
        assert pc.name == "Master"

    # ── Master (3250–3399) ─────────────────────────────────────────────

    def test_master_lower_boundary(self) -> None:
        pc = calc_player_class(3250)
        assert pc.name == "Master"
        assert pc.icon == "💠"
        assert pc.stars == 0
        assert pc.fallback_color == "purple"

    def test_master_one_star(self) -> None:
        pc = calc_player_class(3280)
        assert pc.name == "Master"
        assert pc.stars == 1

    def test_master_max_stars(self) -> None:
        pc = calc_player_class(3370)
        assert pc.name == "Master"
        assert pc.stars == 4

    def test_master_upper_boundary(self) -> None:
        pc = calc_player_class(3399)
        assert pc.name == "Master"
        assert pc.stars == 4

    def test_master_below_is_diamond(self) -> None:
        pc = calc_player_class(3249)
        assert pc.name == "Diamond"

    # ── Diamond (3150–3249) ────────────────────────────────────────────

    def test_diamond_lower_boundary(self) -> None:
        pc = calc_player_class(3150)
        assert pc.name == "Diamond"
        assert pc.icon == "💎"
        assert pc.stars == 0
        assert pc.fallback_color == "blue"

    def test_diamond_one_star(self) -> None:
        pc = calc_player_class(3175)
        assert pc.name == "Diamond"
        assert pc.stars == 1

    def test_diamond_max_stars(self) -> None:
        # 3249 is Diamond upper boundary: (3249-3150)//25 = 99//25 = 3
        pc = calc_player_class(3249)
        assert pc.name == "Diamond"
        assert pc.stars == 3

    def test_diamond_upper_boundary(self) -> None:
        pc = calc_player_class(3249)
        assert pc.name == "Diamond"
        assert pc.stars == 3

    def test_diamond_below_is_platinum(self) -> None:
        pc = calc_player_class(3149)
        assert pc.name == "Platinum"

    # ── Platinum (3050–3149) ───────────────────────────────────────────

    def test_platinum_lower_boundary(self) -> None:
        pc = calc_player_class(3050)
        assert pc.name == "Platinum"
        assert pc.icon == "💿"
        assert pc.stars == 0
        assert pc.fallback_color == "teal"

    def test_platinum_one_star(self) -> None:
        pc = calc_player_class(3075)
        assert pc.name == "Platinum"
        assert pc.stars == 1

    def test_platinum_max_stars(self) -> None:
        pc = calc_player_class(3149)
        assert pc.name == "Platinum"
        # (3149-3050)//25 = 99//25 = 3
        assert pc.stars == 3

    def test_platinum_below_is_gold(self) -> None:
        pc = calc_player_class(3049)
        assert pc.name == "Gold"

    # ── Gold (2950–3049) ───────────────────────────────────────────────

    def test_gold_lower_boundary(self) -> None:
        pc = calc_player_class(2950)
        assert pc.name == "Gold"
        assert pc.icon == "🏆"
        assert pc.stars == 0
        assert pc.fallback_color == "gold"

    def test_gold_one_star(self) -> None:
        pc = calc_player_class(2975)
        assert pc.name == "Gold"
        assert pc.stars == 1

    def test_gold_max_stars(self) -> None:
        pc = calc_player_class(3049)
        assert pc.name == "Gold"
        # (3049-2950)//25 = 99//25 = 3
        assert pc.stars == 3

    def test_gold_below_is_silver(self) -> None:
        pc = calc_player_class(2949)
        assert pc.name == "Silver"

    # ── Silver (2800–2949) ─────────────────────────────────────────────

    def test_silver_lower_boundary(self) -> None:
        pc = calc_player_class(2800)
        assert pc.name == "Silver"
        assert pc.icon == "🥈"
        assert pc.stars == 0
        assert pc.fallback_color == "silver"

    def test_silver_one_star(self) -> None:
        pc = calc_player_class(2830)
        assert pc.name == "Silver"
        assert pc.stars == 1

    def test_silver_max_stars(self) -> None:
        pc = calc_player_class(2949)
        assert pc.name == "Silver"
        # (2949-2800)//30 = 149//30 = 4
        assert pc.stars == 4

    def test_silver_below_is_bronze(self) -> None:
        pc = calc_player_class(2799)
        assert pc.name == "Bronze"

    # ── Bronze (2500–2799) ─────────────────────────────────────────────

    def test_bronze_lower_boundary(self) -> None:
        pc = calc_player_class(2500)
        assert pc.name == "Bronze"
        assert pc.icon == "🥉"
        assert pc.stars == 0
        assert pc.fallback_color == "bronze"

    def test_bronze_one_star(self) -> None:
        pc = calc_player_class(2575)
        assert pc.name == "Bronze"
        assert pc.stars == 1

    def test_bronze_max_stars(self) -> None:
        pc = calc_player_class(2799)
        assert pc.name == "Bronze"
        # (2799-2500)//75 = 299//75 = 3
        assert pc.stars == 3

    def test_bronze_below_is_beginner(self) -> None:
        pc = calc_player_class(2499)
        assert pc.name == "Beginner"

    # ── Beginner (0–2499) ──────────────────────────────────────────────

    def test_beginner_zero(self) -> None:
        pc = calc_player_class(0)
        assert pc.name == "Beginner"
        assert pc.icon == "🔰"
        assert pc.stars == 0
        assert pc.fallback_color == "green"

    def test_beginner_one_star(self) -> None:
        pc = calc_player_class(625)
        assert pc.name == "Beginner"
        assert pc.stars == 1

    def test_beginner_two_star(self) -> None:
        pc = calc_player_class(1250)
        assert pc.name == "Beginner"
        assert pc.stars == 2

    def test_beginner_three_star(self) -> None:
        pc = calc_player_class(1875)
        assert pc.name == "Beginner"
        assert pc.stars == 3

    def test_beginner_max_stars(self) -> None:
        pc = calc_player_class(2499)
        assert pc.name == "Beginner"
        # 2499//625 = 3
        assert pc.stars == 3

    def test_beginner_four_stars_at_2500(self) -> None:
        pc = calc_player_class(2500)
        assert pc.name == "Bronze"
        # Actually, 2500 is Bronze, not Beginner

    # ── Invalid inputs ─────────────────────────────────────────────────

    def test_negative_sp_raises(self) -> None:
        with pytest.raises(ValueError, match="SP must be non-negative"):
            calc_player_class(-1)

    def test_empty_string_rejected(self) -> None:
        """Type system should catch this, but ensure runtime check exists."""
        with pytest.raises(TypeError):
            calc_player_class("")  # type: ignore[arg-type]
