-- 003: Add aliases column to songs
ALTER TABLE songs ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]';
