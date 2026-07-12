# Legacy Database Audit Summary

**Date:** 2026-07-12
**Source:** `/opt/pjsk-emu-bot/data/bot.db` (HK VPS, read-only snapshot)
**SHA-256:** `ecfe3505f0df4b61204185b14576730c2926a818e4f86662c23b98dc8b187a91`

## Table Inventory

| Table | Rows | Notes |
|-------|------|-------|
| users | 154 | All game_id NULL — identity binding gap |
| scores | 2,246 | Personal bests per (game_id, song_id, difficulty) |
| score_history | 2,660 | Full upload history, includes duplicates |
| songs | 695 | title_ja + title_cn + title_en + aliases (JSON) |
| song_difficulties | 3,705 | note_count + constant + const_tag per chart |
| ocr_records | 4,954 | Raw OCR text per upload (for debugging) |
| openid_map | 1 | Not in expected schema — Official QQ OpenID binding |

## Integrity Issues

| Issue | Count | Severity |
|-------|-------|----------|
| NULL game_id (users) | 154 / 154 | **Blocker** — no QQ↔PJSK ID mapping in users table |
| Orphan scores | 2,246 / 2,246 | **Symptom of above** — all scores reference game_ids absent from users |
| Duplicate game_ids | 0 | Clean |
| Invalid scores (negative counts) | 0 | Clean |

## Migration Blockers

1. **Identity mapping gap.** All 154 users have `qq_id` but no `game_id`. The scores table uses `game_id` as the user foreign key. Migration must reconstruct the QQ→PJSK ID mapping, possibly from:
   - OCR records (qq_id → PJSK ID extracted from screenshots)
   - User registration history (if game_id was stored elsewhere)
   - Manual reconciliation

2. **Unrecognized table: openid_map.** Single row mapping OpenID to qq_id. Should be imported into the new `external_identities` table during Phase 3 (Official QQ adapter).

## Data Quality (Positive)

- No duplicate game_id assignments (same PJSK ID registered to multiple QQ)
- Zero invalid judgement counts (no negative perfect/great/good/bad/miss)
- score_history provides full upload audit trail (2,660 records vs 2,246 bests)
- 695 songs × ~5.3 difficulties avg = 3,705 charts — good coverage

## Timestamp Range

- Earliest: 2026-06-25 (Unix 1782343750)
- Latest: 2026-07-12 (Unix 1783757506)
- Span: ~17 days

## Migration Steps (Phase 2)

1. Reconstruct QQ→PJSK ID bindings
2. Import users with resolved game_id
3. Import songs + song_difficulties → charts
4. Convert score_history → score_attempts (all, chronological)
5. Convert scores → personal_bests (recalculate with new rating rules)
6. Reconcile: user count, score count, sampled B20, difficulty rankings
7. Shadow-query new DB against snapshot before cutover
