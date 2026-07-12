-- 002: Performance indices and explicit foreign-key strategy.
--
-- Foreign-key DELETE semantics (documented here because SQLite does not
-- support ALTER TABLE … ADD CONSTRAINT for FK actions without recreating
-- the table):
--
--   external_identities.user_id  → ON DELETE CASCADE   (no user = useless row)
--   charts.song_id               → ON DELETE RESTRICT   (preserve chart data)
--   score_attempts.user_id       → ON DELETE RESTRICT   (preserve history)
--   score_attempts.chart_id      → ON DELETE RESTRICT   (preserve history)
--   personal_bests.user_id       → ON DELETE CASCADE    (derived index)
--   personal_bests.chart_id      → ON DELETE CASCADE    (derived index)
--   personal_bests.best_attempt_id → ON DELETE RESTRICT (don't orphan ref)
--
-- The current SQLite default (NO ACTION, which defers to RESTRICT when no
-- DEFERRABLE is specified) already enforces the RESTRICT semantics above.
-- The CASCADE cases are not yet active — user/chart deletion is not an
-- implemented feature.  When user deletion is added, a future migration
-- must recreate personal_bests and external_identities with the CASCADE
-- actions listed above.

-- Query plan support for common access patterns
CREATE INDEX idx_score_attempts_user_chart ON score_attempts(user_id, chart_id, created_at);
CREATE INDEX idx_score_attempts_user_rating ON score_attempts(user_id, rating DESC);
CREATE INDEX idx_external_identities_user ON external_identities(user_id);
CREATE INDEX idx_charts_difficulty_level ON charts(difficulty, official_level);
CREATE INDEX idx_personal_bests_best_attempt ON personal_bests(best_attempt_id);
