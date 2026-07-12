"""Tests for pjsk_core.domain.ocr — observation, consensus, and candidate ranking."""

import pytest

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import (
    Candidate,
    OcrObservation,
    ValidatedObservation,
    observations_agree,
    rank_candidates,
    validated_observations_agree,
)
from pjsk_core.domain.scores import Judgements


def _obs(
    song_title: str = "Test",
    difficulty: Difficulty = Difficulty.MASTER,
    displayed_level: int = 30,
    perfect: int = 1000,
    great: int = 0,
    good: int = 0,
    bad: int = 0,
    miss: int = 0,
    engine: str = "test",
    elapsed_ms: int = 100,
) -> OcrObservation:
    return OcrObservation(
        song_title=song_title,
        difficulty=difficulty,
        displayed_level=displayed_level,
        judgements=Judgements(perfect=perfect, great=great, good=good, bad=bad, miss=miss),
        engine=engine,
        elapsed_ms=elapsed_ms,
    )


class TestOcrObservation:
    def test_valid_observation(self) -> None:
        obs = OcrObservation(
            song_title="Tell Your World",
            difficulty=Difficulty.MASTER,
            displayed_level=31,
            judgements=Judgements(perfect=1000, great=10, good=0, bad=0, miss=0),
            engine="gemini",
            elapsed_ms=1234,
        )
        assert obs.song_title == "Tell Your World"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 31
        assert obs.judgements.perfect == 1000
        assert obs.engine == "gemini"
        assert obs.elapsed_ms == 1234

    def test_frozen(self) -> None:
        obs = OcrObservation(
            song_title="Test",
            difficulty=Difficulty.EASY,
            displayed_level=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            engine="test",
            elapsed_ms=0,
        )
        with pytest.raises(Exception):
            obs.song_title = "Changed"  # type: ignore[misc]


class TestObservationsAgree:
    def test_identical_observations_agree(self) -> None:
        a = _obs()
        b = _obs()
        assert observations_agree(a, b)

    def test_different_difficulty_disagree(self) -> None:
        a = _obs(difficulty=Difficulty.MASTER)
        b = _obs(difficulty=Difficulty.EXPERT)
        assert not observations_agree(a, b)

    def test_different_judgements_disagree(self) -> None:
        a = _obs(perfect=1000)
        b = _obs(perfect=999, great=1)
        assert not observations_agree(a, b)

    def test_different_displayed_level_disagree(self) -> None:
        a = _obs(displayed_level=30)
        b = _obs(displayed_level=31)
        assert not observations_agree(a, b)

    def test_different_song_title_disagree(self) -> None:
        a = _obs(song_title="Song A")
        b = _obs(song_title="Song B")
        assert not observations_agree(a, b)

    def test_engine_and_elapsed_ignored(self) -> None:
        """Engine name and timing are metadata — they don't affect agreement."""
        a = _obs(engine="gemini", elapsed_ms=500)
        b = _obs(engine="zhipu", elapsed_ms=1200)
        assert observations_agree(a, b)


class TestValidatedObservationsAgree:
    def test_same_chart_agree(self) -> None:
        a = ValidatedObservation(observation=_obs(), matched_chart_id=42, note_validated=True)
        b = ValidatedObservation(observation=_obs(), matched_chart_id=42, note_validated=True)
        assert validated_observations_agree(a, b)

    def test_different_chart_disagree(self) -> None:
        a = ValidatedObservation(observation=_obs(), matched_chart_id=42, note_validated=True)
        b = ValidatedObservation(observation=_obs(), matched_chart_id=99, note_validated=True)
        assert not validated_observations_agree(a, b)

    def test_different_judgements_disagree(self) -> None:
        a = ValidatedObservation(observation=_obs(perfect=1000), matched_chart_id=42, note_validated=True)
        b = ValidatedObservation(observation=_obs(perfect=999, great=1), matched_chart_id=42, note_validated=True)
        assert not validated_observations_agree(a, b)

    def test_frozen(self) -> None:
        v = ValidatedObservation(observation=_obs(), matched_chart_id=1, note_validated=True)
        with pytest.raises(Exception):
            v.matched_chart_id = 2  # type: ignore[misc]


class TestRankCandidates:
    def test_sort_by_model_support_desc(self) -> None:
        c1 = Candidate(
            observation=_obs(), model_support=2, note_validated=True,
            title_similarity=1.0, note_distance=0, matched_chart_id=1,
        )
        c2 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=1.0, note_distance=0, matched_chart_id=2,
        )
        result = rank_candidates([c2, c1])
        assert result[0].model_support == 2
        assert result[1].model_support == 1

    def test_note_validated_first(self) -> None:
        c1 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=0.8, note_distance=0, matched_chart_id=1,
        )
        c2 = Candidate(
            observation=_obs(), model_support=1, note_validated=False,
            title_similarity=1.0, note_distance=10, matched_chart_id=2,
        )
        result = rank_candidates([c2, c1])
        assert result[0].note_validated is True

    def test_title_similarity_desc(self) -> None:
        c1 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=0.9, note_distance=0, matched_chart_id=1,
        )
        c2 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=0.5, note_distance=0, matched_chart_id=2,
        )
        result = rank_candidates([c2, c1])
        assert result[0].title_similarity == 0.9

    def test_note_distance_asc(self) -> None:
        c1 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=0.9, note_distance=0, matched_chart_id=1,
        )
        c2 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=0.9, note_distance=5, matched_chart_id=2,
        )
        result = rank_candidates([c2, c1])
        assert result[0].note_distance == 0

    def test_chart_id_tiebreaker(self) -> None:
        c1 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=1.0, note_distance=0, matched_chart_id=2,
        )
        c2 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=1.0, note_distance=0, matched_chart_id=1,
        )
        result = rank_candidates([c1, c2])
        assert result[0].matched_chart_id == 1

    def test_none_chart_id_sorts_last(self) -> None:
        c1 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=1.0, note_distance=0, matched_chart_id=None,
        )
        c2 = Candidate(
            observation=_obs(), model_support=1, note_validated=True,
            title_similarity=1.0, note_distance=0, matched_chart_id=5,
        )
        result = rank_candidates([c1, c2])
        assert result[0].matched_chart_id == 5
