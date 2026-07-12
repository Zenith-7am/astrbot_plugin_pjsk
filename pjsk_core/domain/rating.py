"""Single-chart Rating (Kn Power / 单曲 SP) — pure calculation rules.

Aligned with old emu-bot src/core/kn_power.py and tests/test_kn_power.py.
"""

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import ScoreStatus


def _parse_constant(community_constant: str) -> tuple[float, str]:
    """Parse "30.5" → (30.5, ""), "32.5+" → (32.5, "+"), "30.1-" → (30.1, "-")."""
    s = community_constant.strip()
    tag = ""
    if s and s[-1] in ("+", "-"):
        tag = s[-1]
        s = s[:-1]
    return float(s), tag


def _calc_clear_s(accuracy: float) -> float:
    """CLEAR bonus factor, capped at 6.5."""
    if accuracy < 90.0:
        return 0.0
    elif accuracy < 97.0:
        return (accuracy - 90.0) / 7.0 * 3.0
    elif accuracy < 100.0:
        return 3.0 + (accuracy - 97.0) / 3.0 * 2.0
    elif accuracy < 100.5:
        return 5.0 + (accuracy - 100.0) / 0.5
    else:
        return 6.5


def calculate_rating(
    official_level: int,
    community_constant: str,
    status: ScoreStatus,
    accuracy: float,
    difficulty: Difficulty,
) -> float:
    """Calculate single-chart Rating (单曲 SP / Kn Power).

    Args:
        official_level: Displayed difficulty level (e.g. 30 for MASTER 30).
        community_constant: Community-researched precise constant (e.g. "30.5+").
        status: AP, FC, or CLEAR.
        accuracy: Achievement rate percentage (e.g. 100.5 for 100.5%).
        difficulty: Chart difficulty — only MAS/APD/EXP AP gets constant bonus.

    Returns:
        Single-chart rating value.
    """
    const_val, tag = _parse_constant(community_constant)
    int_level = official_level

    # Use constant for decimal part; fall back to level if constant is suspicious.
    lv_float = const_val if const_val > 10 else float(int_level)
    decimal_part = lv_float - int_level

    tag_bonus: float
    if tag == "+":
        tag_bonus = 0.05
    elif tag == "-":
        tag_bonus = -0.05
    else:
        tag_bonus = 0.0

    const_bonus = decimal_part + tag_bonus

    if status is ScoreStatus.AP:
        if difficulty not in (Difficulty.MASTER, Difficulty.APPEND, Difficulty.EXPERT):
            const_bonus = 0.0
        return int_level * 101 + round(const_bonus * 20) + 70
    elif status is ScoreStatus.FC:
        s = 0.0
        if accuracy > 100.5:
            s = min(3.0, max(0.0, (accuracy - 100.5) * 6))
        return int_level * (98 + s)
    else:
        return int_level * (90.0 + _calc_clear_s(accuracy))
