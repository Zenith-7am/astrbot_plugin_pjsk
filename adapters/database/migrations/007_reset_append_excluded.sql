-- 007: Reset append_excluded to the confirmed rule default.
-- Migration 006 auto-flipped append_excluded=0 for users with
-- existing APPEND scores.  The confirmed rule is: APPEND is
-- excluded by default and may ONLY be turned on by explicit user
-- action.  This migration reverts everyone to the default.
UPDATE users SET append_excluded = 1;
