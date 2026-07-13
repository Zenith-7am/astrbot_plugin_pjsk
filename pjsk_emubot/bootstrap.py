"""Composition Root — hand-wired dependency assembly.

This is the ONLY place where concrete adapters are instantiated.
Everything else in plugin/ depends on ports and application interfaces.

The database path is resolved from AstrBot's ``data/plugin_data/``
convention (with a local fallback for dev/testing).  On first install,
migrations 001–005 are applied and the 1,533 chart constant rows are
imported from ``chart_data/``.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

from adapters.cache.memory_candidate_store import MemoryCandidateStore
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.ocr_run_repository import SqliteOcrRunRepository
from adapters.database.repository import (
    SqliteChartRepository,
    SqliteScoreRepository,
    SqliteUserRepository,
)
from adapters.resilience.memory_circuit_breaker import MemoryCircuitBreaker
from adapters.vision.gemini import GeminiVisionEngine
from adapters.vision.dashscope import DashScopeVisionEngine
from adapters.vision.stepfun import StepFunVisionEngine
from adapters.vision.zhipu import ZhipuVisionEngine
from pjsk_core.application.confirm_candidate import ConfirmCandidate
from pjsk_core.application.ocr_run_recorder import OcrRunRecorder
from pjsk_core.application.recognize_score import RecognizeScore
from pjsk_core.application.validate_ocr import ValidationPipeline
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy
from pjsk_core.application.vision_race import EngineRuntime, VisionRace
from pjsk_emubot.ephemeral import EphemeralImageBuffer
from pjsk_emubot.rate_limiter import UserRateLimiter
from pjsk_emubot.runtime import PluginRuntime

_logger = logging.getLogger(__name__)

PLUGIN_NAME = "astrbot_plugin_pjsk"
PLUGIN_VERSION = "0.1.0-alpha.1"


# ── Path resolution ─────────────────────────────────────────────────────────


def _resolve_db_path() -> Path:
    """Return the database path using AstrBot's plugin-data convention.

    In production (AstrBot ≥ 4.16): ``data/plugin_data/astrbot_plugin_pjsk/pjsk.db``.
    In dev/testing (no AstrBot import): ``data/pjsk.db``.
    The parent directory is created if it does not exist.
    """
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        base = Path(get_astrbot_data_path())
    except ImportError:
        base = Path("data")
    plugin_data = base / "plugin_data" / PLUGIN_NAME
    plugin_data.mkdir(parents=True, exist_ok=True)
    return plugin_data / "pjsk.db"


def _chart_data_dir() -> Path:
    """Return the ``chart_data/`` directory shipped with the plugin."""
    return Path(__file__).parent.parent / "chart_data"


# ── Config helpers ───────────────────────────────────────────────────────────


def _read_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge AstrBot WebUI config with environment-variable fallbacks.

    API keys are read from env vars first (dev convenience), then from
    the config dict (WebUI settings).  Numeric values use config defaults
    when the key is absent.
    """
    import os

    cfg: dict[str, Any] = dict(config) if config else {}

    # API keys — env vars take precedence (dev / CI)
    if not cfg.get("gemini_api_key"):
        cfg["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")
    if not cfg.get("zhipu_api_key"):
        cfg["zhipu_api_key"] = os.environ.get("ZHIPU_API_KEY", "")
    if not cfg.get("stepfun_api_key"):
        cfg["stepfun_api_key"] = os.environ.get("STEPFUN_API_KEY", "")

    return cfg


# ── Assembly ─────────────────────────────────────────────────────────────────


async def assemble_plugin_runtime(
    config: dict[str, Any] | None = None,
) -> PluginRuntime:
    """Build all dependencies and return a PluginRuntime.

    Called once at plugin startup.  Handles first-install initialisation
    (migrations + chart-data import) and emits a startup log line.
    """
    cfg = _read_config(config)

    user_conn: aiosqlite.Connection | None = None
    chart_conn: aiosqlite.Connection | None = None
    score_conn: aiosqlite.Connection | None = None
    http_client: httpx.AsyncClient | None = None
    runtime: PluginRuntime | None = None

    db_path = _resolve_db_path()

    try:
        # ── Database: migrate + first-install chart import ────────────
        schema_version = await run_migrations(db_path)

        # Check whether charts table is empty (first install)
        chart_count = 0
        init_conn = await get_connection(db_path)
        try:
            rows = list(await init_conn.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM charts"
            ))
            chart_count = rows[0]["cnt"] if rows else 0
        finally:
            await init_conn.close()

        chart_data_ver = "none"
        if chart_count == 0:
            _logger.info(
                "[PJSK] first install detected — importing chart constants …"
            )
            from tools.import_chart_data import import_chart_data
            result = await import_chart_data(db_path, _chart_data_dir())
            _logger.info(
                "[PJSK] chart import complete: inserted=%d updated=%d unchanged=%d",
                result["inserted"], result["updated"], result["unchanged"],
            )
            chart_count = result["inserted"] + result["updated"] + result["unchanged"]

        # Read chart_data version for logging
        try:
            import json
            manifest = json.loads(
                (_chart_data_dir() / "manifest.json").read_text(encoding="utf-8"),
            )
            chart_data_ver = manifest.get("version", "unknown")
        except Exception:
            chart_data_ver = "unknown"

        # ── Connections (independent per repository) ──────────────────
        user_conn = await get_connection(db_path)
        chart_conn = await get_connection(db_path)
        score_conn = await get_connection(db_path)

        user_repo = SqliteUserRepository(user_conn)
        chart_repo = SqliteChartRepository(chart_conn)
        score_repo = SqliteScoreRepository(score_conn)
        ocr_run_repo = SqliteOcrRunRepository(db_path)

        # ── Vision Engines ────────────────────────────────────────────
        gemini_key = cfg.get("gemini_api_key", "")
        zhipu_key = cfg.get("zhipu_api_key", "")
        stepfun_key = cfg.get("stepfun_api_key", "")

        gemini_model = cfg.get("gemini_model", "2.5-flash")
        zhipu_model = cfg.get("zhipu_model", "glm-4.6v-flash")
        stepfun_model = cfg.get("stepfun_model", "step-1v-32k")

        ocr_timeout = float(cfg.get("ocr_timeout_seconds", 15))
        ocr_concurrency = int(cfg.get("ocr_concurrency", 3))

        http_client = httpx.AsyncClient(timeout=30.0)
        breaker = MemoryCircuitBreaker()

        engines: list[EngineRuntime] = []
        enabled_names: list[str] = []

        if gemini_key:
            gemini_eng = GeminiVisionEngine(
                api_key=gemini_key, model=gemini_model, client=http_client,
            )
            engines.append(EngineRuntime(
                engine=gemini_eng,
                policy=EnginePolicy(
                    "gemini-" + gemini_model, 1, True, ocr_timeout, 3,
                ),
                semaphore=asyncio.Semaphore(ocr_concurrency),
            ))
            enabled_names.append("gemini-" + gemini_model)
        if zhipu_key:
            zhipu_eng = ZhipuVisionEngine(
                api_key=zhipu_key, model=zhipu_model, client=http_client,
                thinking_enabled=bool(cfg.get("zhipu_thinking", False)),
            )
            engines.append(EngineRuntime(
                engine=zhipu_eng,
                policy=EnginePolicy(
                    "zhipu-" + zhipu_model, 2, True, ocr_timeout, 3,
                ),
                semaphore=asyncio.Semaphore(ocr_concurrency),
            ))
            enabled_names.append("zhipu-" + zhipu_model)
        if stepfun_key:
            stepfun_eng = StepFunVisionEngine(
                api_key=stepfun_key, model=stepfun_model, client=http_client,
            )
            engines.append(EngineRuntime(
                engine=stepfun_eng,
                policy=EnginePolicy(
                    "stepfun-" + stepfun_model, 3, True, ocr_timeout, 3,
                ),
                semaphore=asyncio.Semaphore(ocr_concurrency),
            ))
            enabled_names.append("stepfun-" + stepfun_model)

        dashscope_key = cfg.get("dashscope_api_key", "")
        dashscope_model = cfg.get("dashscope_model", "qwen3-vl-flash")
        if dashscope_key:
            ds_eng = DashScopeVisionEngine(
                api_key=dashscope_key, model=dashscope_model,
                client=http_client,
                thinking_enabled=bool(cfg.get("dashscope_thinking", False)),
            )
            # Priority 4 (lowest), matches StepFun concurrency
            engines.append(EngineRuntime(
                engine=ds_eng,
                policy=EnginePolicy(
                    "dashscope-" + dashscope_model, 4, True, ocr_timeout, 3,
                ),
                semaphore=asyncio.Semaphore(ocr_concurrency),
            ))
            enabled_names.append("dashscope-" + dashscope_model)

        validator = ValidationPipeline(charts=chart_repo)
        race: VisionRace | None = None
        if engines:
            threshold = 2 if len(engines) >= 2 else 1
            policy = VisionRacePolicy(
                engines=tuple(e.policy for e in engines),
                global_timeout_seconds=30.0,
                consensus_threshold=threshold,
            )
            race = VisionRace(
                runtimes=engines, breaker=breaker, validator=validator,
                policy=policy,
            )

        # ── Application Use Cases ─────────────────────────────────────
        candidate_ttl = int(cfg.get("candidate_ttl_seconds", 300))
        recorder = OcrRunRecorder(ocr_run_repo)
        candidate_store = MemoryCandidateStore()
        recognize_score: RecognizeScore | None = None
        if race is not None:
            recognize_score = RecognizeScore(
                race=race, scores=score_repo,
                recorder=recorder, store=candidate_store, charts=chart_repo,
                candidate_ttl_seconds=candidate_ttl,
            )
        confirm_candidate = ConfirmCandidate(
            store=candidate_store, scores=score_repo, charts=chart_repo,
        )

        # ── Plugin Infrastructure ─────────────────────────────────────
        cooldown = float(cfg.get("user_cooldown_seconds", 5))
        image_buffer = EphemeralImageBuffer()

        runtime = PluginRuntime(
            user_repo=user_repo,
            chart_repo=chart_repo,
            score_repo=score_repo,
            ocr_run_repo=ocr_run_repo,
            recognize_score=recognize_score,
            confirm_candidate=confirm_candidate,
            candidate_store=candidate_store,
            image_buffer=image_buffer,
            rate_limiter=UserRateLimiter(cooldown_seconds=cooldown),
            http_client=http_client,
            db_conn=user_conn,
            chart_db_conn=chart_conn,
            score_db_conn=score_conn,
        )

        # ── Startup log (no secrets) ───────────────────────────────────
        engine_list = ", ".join(enabled_names) if enabled_names else "(none)"
        _logger.info(
            "[PJSK] v%s starting  schema_version=%d  chart_data=%s  charts=%d",
            PLUGIN_VERSION, schema_version, chart_data_ver, chart_count,
        )
        _logger.info("[PJSK] engines: %s", engine_list)

        return runtime

    except Exception:
        if runtime is not None:
            await runtime.close()
        if http_client is not None:
            await http_client.aclose()
        for conn in (user_conn, chart_conn, score_conn):
            if conn is not None:
                await conn.close()
        raise
