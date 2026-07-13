"""Tests for CandidatePresenter."""
from pjsk_emubot.candidate_presenter import CandidatePresenter
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import Candidate, OcrObservation
from pjsk_core.domain.scores import Judgements
from pjsk_core.ports.cache import CandidateSet


def _candidate(title: str, chart_id: int, difficulty: Difficulty) -> Candidate:
    return Candidate(
        observation=OcrObservation(
            title, difficulty, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        ),
        model_support=2, note_validated=True,
        title_similarity=1.0, note_distance=0,
        matched_chart_id=chart_id,
    )


def _candidate_set() -> CandidateSet:
    return CandidateSet(
        candidates=(
            _candidate("Tell Your World", 1, Difficulty.MASTER),
            _candidate("テルユアワールド", 1, Difficulty.MASTER),
            _candidate("Tell Your World", 2, Difficulty.EXPERT),
        ),
        image_sha256="a" * 64, source_gateway="astrbot",
        ocr_run_id=1, chart_data_version="v1",
    )


class TestCandidatePresenter:
    def test_format_includes_short_id_and_numbers(self) -> None:
        cs = _candidate_set()
        text = CandidatePresenter.format(cs, "3b7f")
        assert "3b7f" in text
        assert "1." in text
        assert "2." in text
        assert "3." in text
        assert "Tell Your World" in text
        assert "MASTER" in text
        assert "EXPERT" in text

    def test_parse_numeric_selection(self) -> None:
        cs = _candidate_set()
        assert CandidatePresenter.parse_selection("2", cs, "3b7f") == 1  # 0-based

    def test_parse_numeric_out_of_range(self) -> None:
        cs = _candidate_set()
        assert CandidatePresenter.parse_selection("5", cs, "3b7f") is None
        assert CandidatePresenter.parse_selection("0", cs, "3b7f") is None

    def test_parse_explicit_with_id(self) -> None:
        cs = _candidate_set()
        assert CandidatePresenter.parse_selection("选 3b7f 2", cs, "3b7f") == 1

    def test_parse_explicit_wrong_id(self) -> None:
        cs = _candidate_set()
        # Wrong candidate_set_id -> no match
        assert CandidatePresenter.parse_selection("选 xyz1 2", cs, "3b7f") is None

    def test_parse_non_numeric_text_passes_through(self) -> None:
        cs = _candidate_set()
        assert CandidatePresenter.parse_selection("hello", cs, "3b7f") is None
