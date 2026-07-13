"""SQLite-backed OcrRunRepository -- independent connections per operation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from adapters.database.connection import get_connection
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


class SqliteOcrRunRepository:
    """OcrRunRepository backed by independent aiosqlite connections.

    Each ``save()`` opens its own connection so concurrent saves and
    saves interleaved with ScoreRepository operations never conflict.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        conn = await get_connection(self._db_path)
        try:
            await conn.execute("BEGIN")
            cursor = await conn.execute(
                """INSERT INTO ocr_runs
                   (user_id, image_sha256, source_gateway, final_state,
                    selected_engine, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record.user_id.value, record.image_sha256,
                    record.source_gateway, record.final_state,
                    record.selected_engine, record.created_at.isoformat(),
                ),
            )
            run_id = cursor.lastrowid
            if run_id is None:
                raise RuntimeError("INSERT did not return a row id")

            for obs in record.observations:
                await conn.execute(
                    """INSERT INTO ocr_observations
                       (ocr_run_id, engine_id, provider, result_status,
                        elapsed_ms, song_title, difficulty, displayed_level,
                        perfect, great, good, bad, miss,
                        matched_chart_id, validation_status, error_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, obs.engine_id, obs.provider,
                        obs.result_status, obs.elapsed_ms,
                        obs.song_title,
                        obs.difficulty.value if obs.difficulty else None,
                        obs.displayed_level,
                        obs.judgements.perfect if obs.judgements else None,
                        obs.judgements.great if obs.judgements else None,
                        obs.judgements.good if obs.judgements else None,
                        obs.judgements.bad if obs.judgements else None,
                        obs.judgements.miss if obs.judgements else None,
                        obs.matched_chart_id, obs.validation_status,
                        obs.error_type,
                    ),
                )

            await conn.commit()
            return OcrRunRecord(
                id=run_id, user_id=record.user_id,
                image_sha256=record.image_sha256,
                source_gateway=record.source_gateway,
                final_state=record.final_state,
                selected_engine=record.selected_engine,
                observations=record.observations,
                created_at=record.created_at,
            )
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        conn = await get_connection(self._db_path)
        try:
            rows = list(await conn.execute_fetchall(
                "SELECT * FROM ocr_runs WHERE id = ?", (run_id,)
            ))
            if not rows:
                return None
            run_row = rows[0]

            obs_rows = list(await conn.execute_fetchall(
                "SELECT * FROM ocr_observations WHERE ocr_run_id = ? "
                "ORDER BY id", (run_id,)
            ))

            observations = tuple(
                OcrEngineRecord(
                    engine_id=r["engine_id"], provider=r["provider"],
                    result_status=r["result_status"],
                    elapsed_ms=r["elapsed_ms"],
                    song_title=r["song_title"],
                    difficulty=Difficulty(r["difficulty"]) if r["difficulty"] else None,
                    displayed_level=r["displayed_level"],
                    judgements=(
                        Judgements(
                            perfect=r["perfect"], great=r["great"],
                            good=r["good"], bad=r["bad"], miss=r["miss"],
                        )
                        if r["perfect"] is not None
                        else None
                    ),
                    matched_chart_id=r["matched_chart_id"],
                    validation_status=r["validation_status"],
                    error_type=r["error_type"],
                )
                for r in obs_rows
            )

            return OcrRunRecord(
                id=run_row["id"], user_id=UserId(run_row["user_id"]),
                image_sha256=run_row["image_sha256"],
                source_gateway=run_row["source_gateway"],
                final_state=run_row["final_state"],
                selected_engine=run_row["selected_engine"],
                observations=observations,
                created_at=datetime.fromisoformat(run_row["created_at"]),
            )
        finally:
            await conn.close()
