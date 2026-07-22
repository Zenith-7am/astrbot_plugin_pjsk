"""Fix placeholder community_constant values in 7 charts and recalculate affected AP ratings.

Run on production server:
    cd /opt/pjsk-astrbot/current
    .venv/bin/python tools/fix_placeholder_constants.py /opt/pjsk-astrbot/shared/data/pjsk.db
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# -- project root for domain imports ------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from pjsk_core.domain.charts import Difficulty  # noqa: E402
from pjsk_core.domain.rating import calculate_rating  # noqa: E402
from pjsk_core.domain.scores import ScoreStatus  # noqa: E402

# -- affected chart_id → (difficulty, official_level, corrected_constant) -----
FIXES: dict[int, tuple[str, int, str]] = {
    867: ("expert", 21, "21.0"),   # アサガオの散る頃に
    866: ("expert", 24, "24.0"),   # どんな結末がお望みだい？
    864: ("expert", 25, "25.0"),   # 永遠甚だしい
    863: ("expert", 24, "24.0"),   # ひかりのあつめかた
    862: ("expert", 24, "24.0"),   # オールイン・ワン
    289: ("master", 26, "26.0"),   # アサガオの散る頃に
    288: ("master", 28, "28.0"),   # どんな結末がお望みだい？
}


def main(db_path: str) -> None:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    # ── 1. Update chart constants ────────────────────────────────────────
    chart_ids = list(FIXES.keys())
    print(f"[1/4] Updating {len(chart_ids)} chart community_constants …")
    for cid, (_diff, _level, new_const) in FIXES.items():
        db.execute(
            "UPDATE charts SET community_constant = ? WHERE id = ?",
            (new_const, cid),
        )
        print(f"  chart_id={cid} → {new_const}")

    # ── 2. Find all AP scores on affected charts ──────────────────────────
    placeholders = ",".join("?" * len(chart_ids))
    rows = db.execute(
        f"""SELECT sa.id, sa.user_id, sa.chart_id,
                   sa.perfect, sa.great, sa.good, sa.bad, sa.miss,
                   sa.accuracy, sa.rating AS old_rating, sa.status,
                   c.difficulty, c.official_level, c.community_constant,
                   s.title_ja
            FROM score_attempts sa
            JOIN charts c ON c.id = sa.chart_id
            JOIN songs s ON s.id = c.song_id
            WHERE sa.chart_id IN ({placeholders})
              AND sa.status = 'ap'
            ORDER BY sa.id""",
        chart_ids,
    ).fetchall()

    print(f"\n[2/4] Found {len(rows)} AP score(s) to recalculate …")

    # ── 3. Recalculate & update score_attempts ────────────────────────────
    changed_attempts: dict[int, float] = {}  # attempt_id → new_rating
    affected_users: set[int] = set()
    affected_charts: set[int] = set()

    for r in rows:
        new_rating = calculate_rating(
            official_level=r["official_level"],
            community_constant=r["community_constant"],
            status=ScoreStatus.AP,
            accuracy=r["accuracy"],
            difficulty=Difficulty(r["difficulty"]),
        )
        diff = new_rating - r["old_rating"]
        if abs(diff) > 0.05:
            changed_attempts[r["id"]] = new_rating
            affected_users.add(r["user_id"])
            affected_charts.add(r["chart_id"])
            print(
                f"  attempt_id={r['id']}  user={r['user_id']}  {r['title_ja']} "
                f"{r['difficulty']}{r['official_level']}  "
                f"acc={r['accuracy']:.2f}%  "
                f"old={r['old_rating']:.1f} → new={new_rating:.1f}  "
                f"({diff:+.1f})"
            )
        else:
            print(
                f"  attempt_id={r['id']}  user={r['user_id']}  {r['title_ja']} "
                f"{r['difficulty']}{r['official_level']}  "
                f"acc={r['accuracy']:.2f}%  rating={r['old_rating']:.1f}  (unchanged)"
            )

    if not changed_attempts:
        print("\n  No rating changes needed — all AP scores already correct.")
        db.commit()
        db.close()
        return

    for aid, new_rating in changed_attempts.items():
        db.execute(
            "UPDATE score_attempts SET rating = ? WHERE id = ?",
            (new_rating, aid),
        )
    print(f"\n[3/4] Updated {len(changed_attempts)} score_attempts ratings.")

    # ── 4. Recalculate personal_bests for affected (user, chart) pairs ────
    pb_updated = 0
    for uid in affected_users:
        for cid in affected_charts:
            # Find the best AP/FC attempt for this (user, chart) after rating recalc
            best = db.execute(
                """SELECT sa.id, sa.rating, sa.accuracy, sa.status
                   FROM score_attempts sa
                   JOIN personal_bests pb ON pb.best_attempt_id = sa.id
                   WHERE pb.user_id = ? AND pb.chart_id = ?
                   LIMIT 1""",
                (uid, cid),
            ).fetchone()

            if best is None:
                continue

            # The current PB might still be the best, just with updated rating.
            # Fetch the highest-rated FC/AP attempt for this chart.
            top = db.execute(
                """SELECT id, rating, accuracy, status
                   FROM score_attempts
                   WHERE user_id = ? AND chart_id = ?
                     AND status IN ('ap', 'fc')
                   ORDER BY rating DESC
                   LIMIT 1""",
                (uid, cid),
            ).fetchone()

            if top is None:
                continue

            if top["id"] != best["id"] or abs(top["rating"] - best["rating"]) > 0.05:
                db.execute(
                    """UPDATE personal_bests
                       SET best_attempt_id = ?, accuracy = ?, rating = ?, status = ?,
                           updated_at = datetime('now')
                       WHERE user_id = ? AND chart_id = ?""",
                    (top["id"], top["accuracy"], top["rating"], top["status"], uid, cid),
                )
                pb_updated += 1
                print(
                    f"  PB  user={uid} chart={cid}: "
                    f"attempt {best['id']} → {top['id']} "
                    f"rating {best['rating']:.1f} → {top['rating']:.1f}"
                )
            else:
                # Same attempt, just update the rating/accuracy fields
                db.execute(
                    """UPDATE personal_bests
                       SET accuracy = ?, rating = ?, status = ?,
                           updated_at = datetime('now')
                       WHERE user_id = ? AND chart_id = ?""",
                    (top["accuracy"], top["rating"], top["status"], uid, cid),
                )
                pb_updated += 1
                print(
                    f"  PB  user={uid} chart={cid}: "
                    f"rating updated to {top['rating']:.1f} (same attempt {top['id']})"
                )

    print(f"\n[4/4] Updated {pb_updated} personal_bests.")

    db.commit()
    db.close()
    print("\nDone. All fixes committed.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-pjsk.db>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
