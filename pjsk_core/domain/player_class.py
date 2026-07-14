"""PlayerClass value object and SP-based classification for Project SEKAI."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerClass:
    """A player tier determined by SEKAI POWER (SP)."""

    name: str
    icon: str
    stars: int
    fallback_color: str


# ── Tier definitions ────────────────────────────────────────────────────


@dataclass
class _Tier:
    """Internal tier definition used by calc_player_class."""

    low: float
    high: float
    name: str
    icon: str
    color: str
    stars_fn: Callable[[float], int]


_TIERS: list[_Tier] = [
    _Tier(
        low=3939,
        high=float("inf"),
        name="SEKAI MASTER",
        icon="🌐",
        color="blue",
        stars_fn=lambda _: 10,
    ),
    _Tier(
        low=3400,
        high=3938,
        name="Grand Master",
        icon="👑",
        color="purple",
        stars_fn=lambda sp: int(min(9, (sp - 3400) // 50 + 1)),
    ),
    _Tier(
        low=3250,
        high=3399,
        name="Master",
        icon="💠",
        color="purple",
        stars_fn=lambda sp: int(min(4, (sp - 3250) // 30)),
    ),
    _Tier(
        low=3150,
        high=3249,
        name="Diamond",
        icon="💎",
        color="blue",
        stars_fn=lambda sp: int(min(4, (sp - 3150) // 25)),
    ),
    _Tier(
        low=3050,
        high=3149,
        name="Platinum",
        icon="💿",
        color="teal",
        stars_fn=lambda sp: int(min(4, (sp - 3050) // 25)),
    ),
    _Tier(
        low=2950,
        high=3049,
        name="Gold",
        icon="🏆",
        color="gold",
        stars_fn=lambda sp: int(min(4, (sp - 2950) // 25)),
    ),
    _Tier(
        low=2800,
        high=2949,
        name="Silver",
        icon="🥈",
        color="silver",
        stars_fn=lambda sp: int(min(4, (sp - 2800) // 30)),
    ),
    _Tier(
        low=2500,
        high=2799,
        name="Bronze",
        icon="🥉",
        color="bronze",
        stars_fn=lambda sp: int(min(4, (sp - 2500) // 75)),
    ),
    _Tier(
        low=0,
        high=2499,
        name="Beginner",
        icon="🔰",
        color="green",
        stars_fn=lambda sp: int(min(4, sp // 625)),
    ),
]


def calc_player_class(sp: float) -> PlayerClass:
    """Classify a player by SEKAI POWER (SP).

    Args:
        sp: The player's SEKAI POWER value (non-negative float).

    Returns:
        A PlayerClass dataclass with the matching tier.
    """
    if sp < 0:
        raise ValueError(f"SP must be non-negative, got: {sp}")

    for tier in _TIERS:
        if tier.low <= sp <= tier.high:
            return PlayerClass(
                name=tier.name,
                icon=tier.icon,
                stars=tier.stars_fn(sp),
                fallback_color=tier.color,
            )

    # Fallback (should never reach here given the first tier covers infinity)
    return PlayerClass(
        name="SEKAI MASTER", icon="🌐", stars=10, fallback_color="blue"
    )
