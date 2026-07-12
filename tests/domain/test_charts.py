"""Tests for pjsk_core.domain.charts — difficulty and chart types."""

import pytest
from pjsk_core.domain.charts import Chart, Difficulty


class TestDifficulty:
    def test_six_members(self) -> None:
        members = list(Difficulty)
        assert len(members) == 6
        names = {m.name for m in members}
        assert names == {"EASY", "NORMAL", "HARD", "EXPERT", "MASTER", "APPEND"}

    def test_values_are_lowercase(self) -> None:
        for member in Difficulty:
            assert member.value == member.name.lower()

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("easy", Difficulty.EASY),
            ("normal", Difficulty.NORMAL),
            ("hard", Difficulty.HARD),
            ("expert", Difficulty.EXPERT),
            ("master", Difficulty.MASTER),
            ("append", Difficulty.APPEND),
        ],
    )
    def test_from_string(self, value: str, expected: Difficulty) -> None:
        assert Difficulty(value) is expected


class TestChart:
    def test_valid_chart(self) -> None:
        chart = Chart(
            id=1,
            song_id=42,
            difficulty=Difficulty.MASTER,
            official_level=31,
            community_constant="31.2",
            note_count=1200,
            data_version="2026-07-01",
        )
        assert chart.id == 1
        assert chart.song_id == 42
        assert chart.difficulty == Difficulty.MASTER
        assert chart.official_level == 31
        assert chart.community_constant == "31.2"
        assert chart.note_count == 1200
        assert chart.data_version == "2026-07-01"

    def test_community_constant_with_plus(self) -> None:
        chart = Chart(
            id=2, song_id=1, difficulty=Difficulty.MASTER,
            official_level=32, community_constant="32.5+", note_count=1000,
            data_version="v1",
        )
        assert chart.community_constant == "32.5+"

    def test_community_constant_with_minus(self) -> None:
        chart = Chart(
            id=3, song_id=1, difficulty=Difficulty.MASTER,
            official_level=30, community_constant="30.1-", note_count=900,
            data_version="v1",
        )
        assert chart.community_constant == "30.1-"

    def test_invalid_official_level_raises(self) -> None:
        with pytest.raises(ValueError):
            Chart(
                id=1, song_id=1, difficulty=Difficulty.EASY,
                official_level=0, community_constant="1.0", note_count=100,
                data_version="v1",
            )

    def test_invalid_note_count_raises(self) -> None:
        with pytest.raises(ValueError):
            Chart(
                id=1, song_id=1, difficulty=Difficulty.EASY,
                official_level=5, community_constant="5.0", note_count=0,
                data_version="v1",
            )

    def test_frozen(self) -> None:
        chart = Chart(
            id=1, song_id=1, difficulty=Difficulty.EXPERT,
            official_level=25, community_constant="25.5", note_count=800,
            data_version="v1",
        )
        with pytest.raises(Exception):
            chart.official_level = 26  # type: ignore[misc]
