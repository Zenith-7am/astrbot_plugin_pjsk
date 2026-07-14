"""Tests for DifficultyRankEntry, DifficultyRanking, and sort_charts_by_constant."""

import pytest

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.difficulty_ranking import (
    DifficultyRankEntry,
    DifficultyRanking,
    sort_charts_by_constant,
)


class TestDifficultyRankEntry:
    def test_is_frozen(self) -> None:
        entry = DifficultyRankEntry(
            song_id=1, song_title="Test", chart_id=1,
            community_constant="31.0", const_tag="",
            official_level=31, note_count=1000,
            personal_best=None, is_played=False,
        )
        with pytest.raises(Exception):
            entry.song_title = "Changed"  # type: ignore[misc]

    def test_unplayed_entry_none_properties(self) -> None:
        entry = DifficultyRankEntry(
            song_id=1, song_title="Test", chart_id=1,
            community_constant="31.0", const_tag="",
            official_level=31, note_count=1000,
            personal_best=None, is_played=False,
        )
        assert entry.status is None
        assert entry.accuracy is None
        assert entry.rating is None


class TestDifficultyRanking:
    def test_is_frozen(self) -> None:
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=31,
            mode="global", entries=(),
        )
        with pytest.raises(Exception):
            ranking.mode = "personal"  # type: ignore[misc]

    def test_played_count(self) -> None:
        e1 = DifficultyRankEntry(
            song_id=1, song_title="A", chart_id=1,
            community_constant="31.0", const_tag="",
            official_level=31, note_count=1000,
            personal_best=None, is_played=True,
        )
        e2 = DifficultyRankEntry(
            song_id=2, song_title="B", chart_id=2,
            community_constant="32.0", const_tag="",
            official_level=31, note_count=1100,
            personal_best=None, is_played=False,
        )
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=31,
            mode="personal", entries=(e1, e2),
        )
        assert ranking.played_count == 1
        assert ranking.total_count == 2


class TestSortChartsByConstant:
    def test_higher_constant_first(self) -> None:
        entries = [
            DifficultyRankEntry(song_id=1, song_title="A", chart_id=1,
                community_constant="31.0", const_tag="", official_level=31,
                note_count=1000, personal_best=None, is_played=False),
            DifficultyRankEntry(song_id=2, song_title="B", chart_id=2,
                community_constant="32.0", const_tag="", official_level=31,
                note_count=1100, personal_best=None, is_played=False),
        ]
        result = sort_charts_by_constant(entries)
        assert result[0].community_constant == "32.0"
        assert result[1].community_constant == "31.0"

    def test_plus_before_none_before_minus(self) -> None:
        """Same base constant: + > none > -."""
        entries = [
            DifficultyRankEntry(song_id=1, song_title="A", chart_id=1,
                community_constant="32.5-", const_tag="-", official_level=32,
                note_count=1000, personal_best=None, is_played=False),
            DifficultyRankEntry(song_id=2, song_title="B", chart_id=2,
                community_constant="32.5", const_tag="", official_level=32,
                note_count=1100, personal_best=None, is_played=False),
            DifficultyRankEntry(song_id=3, song_title="C", chart_id=3,
                community_constant="32.5+", const_tag="+", official_level=32,
                note_count=1200, personal_best=None, is_played=False),
        ]
        result = sort_charts_by_constant(entries)
        assert result[0].community_constant == "32.5+"
        assert result[1].community_constant == "32.5"
        assert result[2].community_constant == "32.5-"

    def test_tie_broken_by_song_id(self) -> None:
        """Same constant: lower song_id first."""
        entries = [
            DifficultyRankEntry(song_id=5, song_title="B", chart_id=2,
                community_constant="31.0", const_tag="", official_level=31,
                note_count=1000, personal_best=None, is_played=False),
            DifficultyRankEntry(song_id=3, song_title="A", chart_id=1,
                community_constant="31.0", const_tag="", official_level=31,
                note_count=1000, personal_best=None, is_played=False),
        ]
        result = sort_charts_by_constant(entries)
        assert result[0].song_id == 3
        assert result[1].song_id == 5

    def test_half_point_ordering(self) -> None:
        """32.5+ > 32.5 > 32.0."""
        entries = [
            DifficultyRankEntry(song_id=1, song_title="A", chart_id=1,
                community_constant="32.0", const_tag="", official_level=32,
                note_count=1000, personal_best=None, is_played=False),
            DifficultyRankEntry(song_id=2, song_title="B", chart_id=2,
                community_constant="32.5", const_tag="", official_level=32,
                note_count=1100, personal_best=None, is_played=False),
            DifficultyRankEntry(song_id=3, song_title="C", chart_id=3,
                community_constant="32.5+", const_tag="+", official_level=32,
                note_count=1200, personal_best=None, is_played=False),
        ]
        result = sort_charts_by_constant(entries)
        assert result[0].community_constant == "32.5+"
        assert result[1].community_constant == "32.5"
        assert result[2].community_constant == "32.0"
