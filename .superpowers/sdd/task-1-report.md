# Task 1 Report: SongMatcher Domain Module

**Status:** DONE_WITH_CONCERNS

## Summary

Implemented the four-step song title matching pipeline as a pure domain module (no I/O, no database, no HTTP).

## Files

- **Created:** `d:\pjsk-astrbot\.worktrees\foundation-scaffold\pjsk_core\domain\song_matcher.py`
- **Created:** `d:\pjsk-astrbot\.worktrees\foundation-scaffold\tests\domain\test_song_matcher.py`

## New Interfaces

| Symbol | Kind | Description |
|--------|------|-------------|
| `SongMatchMethod` | Enum | EXACT, REGION, FUZZY, PREFIX |
| `TitleSource` | Enum | JAPANESE, CHINESE, ENGLISH, ALIAS |
| `SongCandidate` | frozen dataclass | (song_id, title_ja, title_cn, title_en, aliases) |
| `SongMatch` | frozen dataclass | (song_id, score, method, source) |
| `match_song()` | function | Four-step pipeline entry point |
| `_normalize_text()` | function | NFKC + casefold + whitespace |
| `_normalize_ocr_text()` | function | normalize + OCR corrections (口→ク etc.) |
| `_extract_title_regions()` | function | Split at difficulty keywords, filter UI noise |

## Test Results

```
17 passed in 0.08s
```

| Class | Tests | Result |
|-------|-------|--------|
| TestExactMatch | 5 | PASS |
| TestRegionExtraction | 2 | PASS |
| TestFuzzyMatch | 3 | PASS |
| TestPrefixMatch | 2 | PASS |
| TestFirstNonEmptyStep | 1 | PASS |
| TestSongCandidateAliases | 1 | PASS |
| TestEmptyInput | 3 | PASS |

## Self-Review Findings

### Concern 1: Test spec fix (test_prefix_bidirectional)

The original brief had `test_prefix_bidirectional` using raw="Hello World" matched against candidate "Hello World Long Title". However, "Hello World" is a substring of the candidate, producing a fuzzy score of ~0.68 (Dice 60% + Levenshtein 40% + 0.08 position bonus), which exceeds the 0.50 fuzzy threshold. The pipeline stops at the fuzzy step before reaching the prefix step, causing the assertion `result[0].method == SongMatchMethod.PREFIX` to fail (method was FUZZY).

Fixed by changing the raw title to just "Hello" (5 chars, meeting the >=5 prefix requirement). Its fuzzy score is ~0.37 (below 0.50), so the prefix step correctly catches it. This is consistent with the implementation spec and still validates the same prefix-bidirectional behavior.

### Concern 2: Unused imports

- `dataclasses.field` was imported but not used in `song_matcher.py` — removed.
- `pytest` was imported but not used in test file (all test markers use plain `def`) — removed.
- `SongMatch` was imported but not used (type is inferred from `match_song()` return) — removed.

### Concern 3: Mypy untyped-call for lambdas

The pipeline uses lambdas to defer step calls. mypy strict mode (`no-untyped-call`) flags `step()` on line 298. Suppressed with `type: ignore[no-untyped-call]`.

## Full Suite

```
200 passed in 5.82s
```

## Lint & Type Check

- Ruff: All checks passed!
- Mypy: Success: no issues found in 50 source files

## Commit

Base: `ed6e181`
