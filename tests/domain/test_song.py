"""Tests for pjsk_core.domain.song — Song value object."""

import pytest
from pjsk_core.domain.song import Song


class TestSong:
    def test_field_access(self) -> None:
        s = Song(id=1, title_ja="幾望の月", title_cn="", title_en="", aliases="[]")
        assert s.id == 1
        assert s.title_ja == "幾望の月"
        assert s.title_cn == ""
        assert s.title_en == ""
        assert s.aliases == "[]"

    def test_is_frozen(self) -> None:
        s = Song(id=2, title_ja="タイトル", title_cn="", title_en="", aliases="[]")
        with pytest.raises(Exception):
            s.id = 3  # type: ignore[misc]

    def test_equality(self) -> None:
        a = Song(id=1, title_ja="同じ", title_cn="", title_en="", aliases="[]")
        b = Song(id=1, title_ja="同じ", title_cn="", title_en="", aliases="[]")
        assert a == b

    def test_inequality(self) -> None:
        a = Song(id=1, title_ja="A", title_cn="", title_en="", aliases="[]")
        b = Song(id=2, title_ja="B", title_cn="", title_en="", aliases="[]")
        assert a != b

    def test_hashable(self) -> None:
        a = Song(id=1, title_ja="A", title_cn="", title_en="", aliases="[]")
        b = Song(id=1, title_ja="A", title_cn="", title_en="", aliases="[]")
        assert hash(a) == hash(b)
