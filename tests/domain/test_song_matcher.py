"""Song matching tests — aligned with old emu-bot song_match.py fixtures."""
from pjsk_core.domain.song_matcher import (
    SongCandidate, SongMatchMethod, TitleSource, match_song,
)


def _make_candidates(*titles_ja: str) -> tuple[SongCandidate, ...]:
    return tuple(
        SongCandidate(song_id=i + 1, title_ja=t, title_cn="", title_en="")
        for i, t in enumerate(titles_ja)
    )


class TestExactMatch:
    def test_exact_match_ja(self) -> None:
        candidates = _make_candidates("テルミーワールド", "泡沫未来", "初音ミクの消失")
        result = match_song("テルミーワールド", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1
        assert result[0].method == SongMatchMethod.EXACT
        assert result[0].source == TitleSource.JAPANESE
        assert result[0].score == 1.0

    def test_exact_match_casefold(self) -> None:
        candidates = (SongCandidate(1, "Hello World", "", ""),)
        result = match_song("hello world", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1

    def test_exact_match_nfkc(self) -> None:
        """Fullwidth ASCII should normalize to halfwidth via NFKC."""
        candidates = (SongCandidate(1, "ABC123", "", ""),)
        result = match_song("ＡＢＣ１２３", candidates)  # fullwidth
        assert len(result) == 1
        assert result[0].song_id == 1

    def test_ocr_correction_applied_to_raw_only(self) -> None:
        """OCR corrections (口→ク etc.) only transform the raw side.
        Candidate titles with real 口 must NOT be rewritten."""
        # A song whose real title contains 口
        candidates = (SongCandidate(1, "口ード", "", ""),)
        # OCR misreads ク as 口 — after correction, should match
        result = match_song("口ード", candidates)  # raw = OCR output
        assert len(result) == 1
        assert result[0].song_id == 1

    def test_normalization_collision_returns_multiple(self) -> None:
        """Two songs that normalize to the same string should both appear."""
        c = (
            SongCandidate(1, "Test Song", "", ""),
            SongCandidate(2, "test song", "", ""),  # casefold → same
        )
        result = match_song("Test Song", c)
        assert len(result) == 2
        assert {r.song_id for r in result} == {1, 2}


class TestRegionExtraction:
    def test_difficulty_keyword_truncation(self) -> None:
        """MASTER at end of title → stripped for region match."""
        candidates = _make_candidates("初音ミクの消失")
        result = match_song("初音ミクの消失 MASTER", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.REGION

    def test_ui_noise_filtered(self) -> None:
        candidates = _make_candidates("Test")
        result = match_song("PERFECT Test GREAT 1234", candidates)
        assert len(result) >= 1


class TestFuzzyMatch:
    def test_fuzzy_above_threshold(self) -> None:
        candidates = _make_candidates("テルミーワールド")
        result = match_song("テルミーワルド", candidates)  # one char missing
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.FUZZY
        assert result[0].score >= 0.50

    def test_fuzzy_below_threshold_excluded(self) -> None:
        candidates = _make_candidates("テルミーワールド")
        result = match_song("abcdefg", candidates)
        assert len(result) == 0

    def test_fuzzy_position_bonus(self) -> None:
        """Substring match gets +0.08 position bonus."""
        candidates = _make_candidates("Hello World Song")
        result = match_song("Hello World", candidates)
        assert len(result) == 1
        assert result[0].score > 0.60  # Dice is high for substring


class TestPrefixMatch:
    def test_prefix_bidirectional(self) -> None:
        # "Hello" (5 chars) is a bidirectional prefix of "Hello World Long Title"
        # but scores below 0.50 on fuzzy, so prefix step correctly catches it.
        candidates = _make_candidates("Hello World Long Title")
        result = match_song("Hello", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.PREFIX

    def test_prefix_too_short_rejected(self) -> None:
        candidates = _make_candidates("Hello World")
        result = match_song("Hel", candidates)  # only 3 chars
        assert len(result) == 0  # shorter side < 5


class TestFirstNonEmptyStep:
    def test_exact_stops_pipeline(self) -> None:
        """Exact match should prevent fuzzy from polluting results."""
        candidates = _make_candidates("Test", "Testing Song")
        result = match_song("Test", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1
        assert result[0].method == SongMatchMethod.EXACT


class TestSongCandidateAliases:
    def test_alias_match(self) -> None:
        candidates = (
            SongCandidate(1, "初音ミクの消失", "初音未来的消失", "",
                          aliases=("消失", "激唱")),
        )
        result = match_song("消失", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1
        assert result[0].source == TitleSource.ALIAS


class TestPunctuationNormalization:
    """Fullwidth punctuation (!, ?, ~) should normalize to halfwidth
    so that OCR variants like "モア!" match DB "モア！"."""

    def test_fullwidth_exclamation(self) -> None:
        """！(U+FF01) normalizes to !(U+0021) for exact match."""
        candidates = _make_candidates("モア！ジャンプ！モア！")
        # OCR reads with halfwidth ! (no spaces — this is the pure punctuation case)
        result = match_song("モア!ジャンプ!モア!", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.EXACT

    def test_fullwidth_question(self) -> None:
        """？(U+FF1F) normalizes to ?(U+003F) for exact match."""
        candidates = _make_candidates("え？ああ、そう。")
        # OCR reads with halfwidth ?
        result = match_song("え?ああ、そう。", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.EXACT

    def test_wave_dash_to_tilde(self) -> None:
        """～(U+FF5E) normalizes to ~(U+007E) for exact match."""
        candidates = _make_candidates("い～やい～やい～や")
        # OCR reads with tilde
        result = match_song("い~やい~やい~や", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.EXACT


class TestKanaNormalization:
    """Hiragana characters OCR-misread inside katakana words
    should normalize so that "ヒマん" matches "ヒマン"."""

    def test_hiragana_n_in_katakana_word(self) -> None:
        """ん (hiragana) normalizes to ン (katakana) in OCR text."""
        candidates = _make_candidates("ヒマン=ヒダイ焦燥曲")
        result = match_song("ヒマん=ヒダイ焦燥曲", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.EXACT

    def test_multiple_hiragana_in_katakana(self) -> None:
        """All hiragana chars in OCR text normalize to katakana."""
        candidates = _make_candidates("コンニチハ")
        result = match_song("こんにちは", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.EXACT


class TestEmptyInput:
    def test_empty_raw_title_returns_empty(self) -> None:
        candidates = _make_candidates("Test")
        result = match_song("", candidates)
        assert len(result) == 0

    def test_whitespace_raw_title_returns_empty(self) -> None:
        candidates = _make_candidates("Test")
        result = match_song("   ", candidates)
        assert len(result) == 0

    def test_empty_candidates_returns_empty(self) -> None:
        result = match_song("Test", ())
        assert len(result) == 0
