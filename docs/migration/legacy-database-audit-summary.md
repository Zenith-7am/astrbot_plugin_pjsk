# Legacy Database Audit Summary (Corrected)

**Date:** 2026-07-12 · **Corrected:** 2026-07-12
**Source:** `/opt/pjsk-emu-bot/data/bot.db` (HK VPS, read-only snapshot)
**SHA-256:** `ecfe3505f0df4b61204185b14576730c2926a818e4f86662c23b98dc8b187a91`

## Key Discovery: Field Semantics

`scores.game_id` is a **misnamed field** — it stores the **QQ number**, not
the PJSK player ID. Evidence:

- `SELECT COUNT(*) FROM scores s JOIN users u ON s.game_id = u.qq_id` → **2,246/2,246** (100%)
- `SELECT COUNT(*) FROM scores s JOIN users u ON s.game_id = u.game_id` → **0/2,246** (0%)
- Sampled rows confirm `scores.game_id` values match `users.qq_id` pattern, not PJSK game IDs

Migration can directly map `scores.game_id` → the new `users.qq_number` column.
No identity reconstruction needed.

## Table Inventory

| Table | Rows | Notes |
|-------|------|-------|
| users | 154 | qq_id populated; game_id (PJSK) all NULL |
| scores | 2,246 | game_id = QQ number; personal best per (qq, song_id, difficulty) |
| score_history | 2,660 | Full upload history; game_id = QQ number |
| songs | 695 | title_ja + title_cn + title_en + aliases (JSON) |
| song_difficulties | 3,705 | note_count + constant + const_tag per chart |
| ocr_records | 4,954 | Raw OCR text per upload (for debugging) |
| openid_map | 1 | Not in expected schema — Official QQ OpenID binding |

## Integrity

| Check | Count | Status |
|-------|-------|--------|
| Orphan scores (scores.game_id ∉ users.qq_id) | 0 | Clean |
| Null PJSK game_id (users) | 154/154 | Users never bound PJSK ID — non-blocking |
| Duplicate PJSK game_ids | 0 | Clean |
| Invalid scores (negative counts) | 0 | Clean |
| QQ-score linkage coverage | 2,246/2,246 | 100% |
| Timestamp range | 2026-06-25 ~ 2026-07-12 | ~17 days |

## Migration Plan (Simplified)

No identity reconstruction is needed. The old `scores.game_id` is the QQ
number and maps directly to `users.qq_number` in the new schema.

1. Import users: `users.qq_id` → `users.qq_number`
2. Import songs + song_difficulties → charts
3. Convert score_history → score_attempts (all)
4. Convert scores → personal_bests (recalculate with new rules)
5. openid_map → external_identities
6. Reconcile and shadow-query
