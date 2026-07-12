"""Tests for ValidationPipeline — application-layer OCR validation."""

from pjsk_core.application.validate_ocr import (
    ValidationPipeline, ValidationStatus,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.song_matcher import SongCandidate
from pjsk_core.ports.repositories import SongCatalog


class _FakeChartRepository:
    """In-memory fake for testing ValidationPipeline without SQLite."""

    def __init__(self, songs: tuple[SongCandidate, ...], charts: tuple[Chart, ...]) -> None:
        self._catalog_version = "2026-07-12"
        self._songs = songs
        self._charts = charts

    async def get_song_catalog(self) -> SongCatalog:
        return SongCatalog(self._catalog_version, self._songs)

    async def get_by_song_and_difficulty(self, song_id: int, difficulty: Difficulty) -> Chart | None:
        for c in self._charts:
            if c.song_id == song_id and c.difficulty == difficulty:
                return c
        return None

    async def get_by_id(self, chart_id: int) -> Chart | None:
        for c in self._charts:
            if c.id == chart_id:
                return c
        return None

    async def find_by_song_and_difficulty(self, song_title: str, difficulty: Difficulty) -> Chart | None:
        return None  # not needed for validation tests

    async def list_by_difficulty_level(self, difficulty: Difficulty, official_level: int) -> list[Chart]:
        return []  # not needed for validation tests


def _obs(song_title: str = "Test Song", difficulty: Difficulty = Difficulty.MASTER,
         displayed_level: int = 30, perfect: int = 1000, great: int = 100,
         good: int = 0, bad: int = 0, miss: int = 0) -> OcrObservation:
    return OcrObservation(song_title, difficulty, displayed_level,
                          Judgements(perfect, great, good, bad, miss),
                          engine="test", elapsed_ms=500)


def _chart(song_id: int = 1, difficulty: Difficulty = Difficulty.MASTER,
           official_level: int = 30,
           community_constant: str = "30.5", note_count: int = 1100) -> Chart:
    return Chart(id=1, song_id=song_id, difficulty=difficulty,
                 official_level=official_level,
                 community_constant=community_constant,
                 note_count=note_count, data_version="2026-07-12")


class TestValidationPipeline:
    """ValidationPipeline test suite."""

    async def test_exact_match_note_pass_level_pass(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, official_level=30, note_count=1100),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=100)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.STRONG
        assert result.primary is not None
        assert result.primary.note_validated is True
        assert result.primary.level_validated is True

    async def test_note_off_by_one_passes(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, note_count=1101),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=101)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.STRONG
        assert result.primary is not None
        assert result.primary.note_validated is True

    async def test_note_off_by_two_fails(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, note_count=1102),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=100)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.CANDIDATE

    async def test_level_mismatch_is_candidate(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, official_level=31),),  # obs says 30
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", displayed_level=30)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.CANDIDATE

    async def test_no_song_match_rejected(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Completely Different", "", ""),),
            charts=(_chart(song_id=1),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song")
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.REJECTED
        assert result.primary is None

    async def test_first_match_fail_second_succeed(self) -> None:
        """First song match gets note failure, second gets it right.

        Both candidates share the same title_ja, so match_song() returns
        both at the EXACT step (different song_ids).  The pipeline sorts
        by validation quality and picks the passing chart as primary.
        """
        repo = _FakeChartRepository(
            songs=(
                SongCandidate(1, "Test Song", "", ""),
                SongCandidate(2, "Test Song", "", ""),  # same title, diff id
            ),
            charts=(
                _chart(song_id=1, note_count=9999),   # way off
                _chart(song_id=2, note_count=1100),   # correct
            ),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=100)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.STRONG
        assert result.primary is not None
        assert result.primary.song_match.song_id == 2
