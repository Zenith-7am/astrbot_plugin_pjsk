-- 006: Add append_excluded preference column to users
ALTER TABLE users ADD COLUMN append_excluded INTEGER NOT NULL DEFAULT 1;

-- Backfill: users who have played APPEND charts (AP or FC) get
-- append_excluded = 0 (i.e. APPEND is NOT excluded from their
-- rankings).  Everyone else keeps the default of 1 (excluded).
UPDATE users SET append_excluded = 0
WHERE id IN (
    SELECT DISTINCT pb.user_id FROM personal_bests pb
    JOIN charts c ON c.id = pb.chart_id
    WHERE c.difficulty = 'append' AND pb.status IN ('ap', 'fc')
);
