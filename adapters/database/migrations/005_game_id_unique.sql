-- 005: Unique index on users.game_id (non-NULL only)
-- Two different QQ accounts cannot share the same game_id.
-- NULL game_id values (auto-registered, not yet bound) are excluded
-- from the uniqueness constraint — they can coexist freely.

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_game_id_unique
ON users(game_id)
WHERE game_id IS NOT NULL;
