"""Pure song-title matching pipeline — four-step, compatible with old emu-bot."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


# ── Types ────────────────────────────────────────────────────────────────

class SongMatchMethod(Enum):
    EXACT = "exact"
    REGION = "region"
    FUZZY = "fuzzy"
    PREFIX = "prefix"


class TitleSource(Enum):
    JAPANESE = "ja"
    CHINESE = "cn"
    ENGLISH = "en"
    ALIAS = "alias"


@dataclass(frozen=True)
class SongCandidate:
    song_id: int
    title_ja: str
    title_cn: str = ""
    title_en: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SongMatch:
    song_id: int
    score: float
    method: SongMatchMethod
    source: TitleSource


# ── Normalization ────────────────────────────────────────────────────────

_OCR_CORRECTIONS = str.maketrans({"口": "ク", "一": "ー", "才": "オ"})
_RE_WHITESPACE = re.compile(r"\s+")

# Keywords that mark difficulty labels in score screenshots
_DIFFICULTY_KEYWORDS = (
    "MASTER", "EXPERT", "APPEND", "HARD", "NORMAL", "EASY",
    "マスター", "エキスパート", "ハード", "ノーマル", "イージー",
)

# UI noise tokens from result-screen overlays
_UI_NOISE_RE = re.compile(
    r"PERFECT|GREAT|GOOD|BAD|MISS|COMBO|CLEAR|FULL|ALL|\d{1,6}",
    re.IGNORECASE,
)

_METHOD_PRIORITY = {
    SongMatchMethod.EXACT: 0,
    SongMatchMethod.REGION: 1,
    SongMatchMethod.FUZZY: 2,
    SongMatchMethod.PREFIX: 3,
}

_SOURCE_PRIORITY = {
    TitleSource.JAPANESE: 0,
    TitleSource.CHINESE: 1,
    TitleSource.ENGLISH: 2,
    TitleSource.ALIAS: 3,
}


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = _RE_WHITESPACE.sub(" ", text)
    return text.strip()


def _normalize_ocr_text(text: str) -> str:
    return _normalize_text(text).translate(_OCR_CORRECTIONS)


# ── Step helpers ─────────────────────────────────────────────────────────

def _iter_sources(candidate: SongCandidate) -> list[tuple[str, TitleSource]]:
    pairs: list[tuple[str, TitleSource]] = []
    for title, src in [
        (candidate.title_ja, TitleSource.JAPANESE),
        (candidate.title_cn, TitleSource.CHINESE),
        (candidate.title_en, TitleSource.ENGLISH),
    ]:
        if title.strip():
            pairs.append((title, src))
    for alias in candidate.aliases:
        if alias.strip():
            pairs.append((alias, TitleSource.ALIAS))
    return pairs


def _try_exact(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    norm_raw = _normalize_text(raw)
    ocr_raw = _normalize_ocr_text(raw)
    matches: list[SongMatch] = []
    seen: set[int] = set()

    for attempt in (norm_raw, ocr_raw):
        if not attempt:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                if _normalize_text(title) == attempt and c.song_id not in seen:
                    matches.append(SongMatch(c.song_id, 1.0,
                                             SongMatchMethod.EXACT, src))
                    seen.add(c.song_id)
                    break
    return _dedup_sort(matches)


def _try_region(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    regions = _extract_title_regions(raw)
    matches: list[SongMatch] = []
    seen: set[int] = set()
    for region in regions:
        norm_region = _normalize_text(region)
        if not norm_region:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                if _normalize_text(title) == norm_region and c.song_id not in seen:
                    matches.append(SongMatch(c.song_id, 1.0,
                                             SongMatchMethod.REGION, src))
                    seen.add(c.song_id)
                    break
    return _dedup_sort(matches)


def _extract_title_regions(raw: str) -> tuple[str, ...]:
    """Split raw OCR output at difficulty keywords and remove UI noise."""
    # Build a regex that splits at difficulty keywords
    kw_pattern = "|".join(re.escape(kw) for kw in _DIFFICULTY_KEYWORDS)
    parts = re.split(rf"({kw_pattern})", raw, flags=re.IGNORECASE)
    regions: list[str] = []
    for part in parts:
        cleaned = _UI_NOISE_RE.sub(" ", part)
        cleaned = _RE_WHITESPACE.sub(" ", cleaned).strip()
        if cleaned and len(cleaned) >= 2:
            regions.append(cleaned)
    return tuple(dict.fromkeys(regions))  # dedup keeping order


def _try_fuzzy(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    norm_raw = _normalize_text(raw)
    ocr_raw = _normalize_ocr_text(raw)
    best: dict[int, SongMatch] = {}

    for attempt in (norm_raw, ocr_raw):
        if not attempt:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                norm_title = _normalize_text(title)
                if not norm_title:
                    continue
                score = _fuzzy_score(attempt, norm_title)
                if score < 0.50:
                    continue
                if c.song_id not in best or score > best[c.song_id].score:
                    best[c.song_id] = SongMatch(c.song_id, score,
                                                SongMatchMethod.FUZZY, src)
    return _dedup_sort(list(best.values()))


def _fuzzy_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    dice = _dice_coefficient(a, b)
    lev = _levenshtein_similarity(a, b)
    score = dice * 0.6 + lev * 0.4
    # Position bonus
    if a in b or b in a:
        score += 0.08
    return min(1.0, score)


def _dice_coefficient(a: str, b: str) -> float:
    """Dice coefficient on character bigrams."""
    a_bigrams = {a[i:i + 2] for i in range(len(a) - 1)} if len(a) >= 2 else {a}
    b_bigrams = {b[i:i + 2] for i in range(len(b) - 1)} if len(b) >= 2 else {b}
    if not a_bigrams or not b_bigrams:
        return 0.0
    intersection = a_bigrams & b_bigrams
    return 2.0 * len(intersection) / (len(a_bigrams) + len(b_bigrams))


def _levenshtein_similarity(a: str, b: str) -> float:
    """1 - (edit_distance / max(len(a), len(b)))."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    dist = _levenshtein_distance(a, b)
    return 1.0 - dist / max_len


def _levenshtein_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, 1):
        curr[0] = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[-1]


def _try_prefix(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    norm_raw = _normalize_text(raw)
    ocr_raw = _normalize_ocr_text(raw)
    matches: list[SongMatch] = []
    seen: set[int] = set()

    for attempt in (norm_raw, ocr_raw):
        if not attempt:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                norm_title = _normalize_text(title)
                if not norm_title:
                    continue
                shorter = min(attempt, norm_title, key=len)
                longer = max(attempt, norm_title, key=len)
                if len(shorter) < 5:
                    continue
                if longer.startswith(shorter) and c.song_id not in seen:
                    score = len(shorter) / len(longer)
                    matches.append(SongMatch(c.song_id, score,
                                             SongMatchMethod.PREFIX, src))
                    seen.add(c.song_id)
                    break
    return _dedup_sort(matches)


def _dedup_sort(matches: list[SongMatch]) -> list[SongMatch]:
    """Dedup by song_id (keep best), sort by score->method->source->id."""
    best: dict[int, SongMatch] = {}
    for m in matches:
        if m.song_id not in best:
            best[m.song_id] = m
        elif m.score > best[m.song_id].score:
            best[m.song_id] = m
    return sorted(
        best.values(),
        key=lambda m: (
            -m.score,
            _METHOD_PRIORITY[m.method],
            _SOURCE_PRIORITY[m.source],
            m.song_id,
        ),
    )


# ── Public API ───────────────────────────────────────────────────────────

def match_song(
    raw_title: str,
    candidates: Sequence[SongCandidate],
) -> tuple[SongMatch, ...]:
    """Match raw OCR title against song candidates.

    Four-step pipeline -- the first non-empty step wins:
    1. Exact match (safe normalization, then OCR-corrected)
    2. Region extraction (difficulty keyword truncation, UI-noise filtered)
    3. Fuzzy match (Dice 60% + Levenshtein 40%, threshold 0.50)
    4. Prefix match (bidirectional, >=5 chars)
    """
    if not raw_title.strip():
        return ()
    if not candidates:
        return ()

    steps = (
        lambda: _try_exact(raw_title, candidates),
        lambda: _try_region(raw_title, candidates),
        lambda: _try_fuzzy(raw_title, candidates),
        lambda: _try_prefix(raw_title, candidates),
    )
    for step in steps:
        result = step()  # type: ignore[no-untyped-call]
        if result:
            return tuple(result)
    return ()
