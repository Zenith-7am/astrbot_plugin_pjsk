"""Composition Root — hand-wired dependency assembly.

This is the ONLY place where concrete adapters are instantiated.
Everything else in plugin/ depends on ports and application interfaces.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

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
from adapters.vision.stepfun import StepFunVisionEngine
from adapters.vision.zhipu import ZhipuVisionEngine
from pjsk_core.application.confirm_candidate import ConfirmCandidate
from pjsk_core.application.ocr_run_recorder import OcrRunRecorder
from pjsk_core.application.recognize_score import RecognizeScore
from pjsk_core.application.validate_ocr import ValidationPipeline
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy
from pjsk_core.application.vision_race import EngineRuntime, VisionRace
from plugin.ephemeral import EphemeralImageBuffer
from plugin.rate_limiter import UserRateLimiter
from plugin.runtime import PluginRuntime


async def assemble_plugin_runtime(db_path: Path) -> PluginRuntime:
    """Build all dependencies and return a PluginRuntime.

    This is called once at plugin startup (on_astrbot_loaded).
    """
    # ── Database ──────────────────────────────────────────────────
    await run_migrations(db_path)
    conn = await get_connection(db_path)

    user_repo = SqliteUserRepository(conn)
    chart_repo = SqliteChartRepository(conn)
    score_repo = SqliteScoreRepository(conn)
    ocr_run_repo = SqliteOcrRunRepository(db_path)

    # ── Vision Engines ────────────────────────────────────────────
    import os
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    zhipu_key = os.environ.get("ZHIPU_API_KEY", "")
    stepfun_key = os.environ.get("STEPFUN_API_KEY", "")

    http_client = httpx.AsyncClient(timeout=30.0)
    breaker = MemoryCircuitBreaker()

    engines: list[EngineRuntime] = []
    if gemini_key:
        gemini_eng = GeminiVisionEngine(
            api_key=gemini_key, model="2.5-flash", client=http_client,
        )
        engines.append(EngineRuntime(
            engine=gemini_eng,
            policy=EnginePolicy("gemini-2.5-flash", 1, True, 15.0, 3),
            semaphore=asyncio.Semaphore(3),
        ))
    if zhipu_key:
        zhipu_eng = ZhipuVisionEngine(
            api_key=zhipu_key, model="glm-4v-plus", client=http_client,
        )
        engines.append(EngineRuntime(
            engine=zhipu_eng,
            policy=EnginePolicy("zhipu-glm-4v-plus", 2, True, 15.0, 3),
            semaphore=asyncio.Semaphore(3),
        ))
    if stepfun_key:
        stepfun_eng = StepFunVisionEngine(
            api_key=stepfun_key, model="step-1v-32k", client=http_client,
        )
        engines.append(EngineRuntime(
            engine=stepfun_eng,
            policy=EnginePolicy("stepfun-step-1v-32k", 3, True, 15.0, 3),
            semaphore=asyncio.Semaphore(3),
        ))

    policy = VisionRacePolicy(
        engines=tuple(e.policy for e in engines),
        global_timeout_seconds=30.0,
        consensus_threshold=2,
    )

    validator = ValidationPipeline(charts=chart_repo)
    race = VisionRace(runtimes=engines, breaker=breaker, validator=validator, policy=policy)

    # ── Application Use Cases ─────────────────────────────────────
    recorder = OcrRunRecorder(ocr_run_repo)
    candidate_store = MemoryCandidateStore()
    recognize_score = RecognizeScore(
        race=race, scores=score_repo,
        recorder=recorder, store=candidate_store, charts=chart_repo,
        candidate_ttl_seconds=300,
    )
    confirm_candidate = ConfirmCandidate(
        store=candidate_store, scores=score_repo, charts=chart_repo,
    )

    # ── Plugin Infrastructure ─────────────────────────────────────
    image_buffer = EphemeralImageBuffer()

    return PluginRuntime(
        user_repo=user_repo,
        chart_repo=chart_repo,
        score_repo=score_repo,
        ocr_run_repo=ocr_run_repo,
        recognize_score=recognize_score,
        confirm_candidate=confirm_candidate,
        candidate_store=candidate_store,
        image_buffer=image_buffer,
        rate_limiter=UserRateLimiter(),
        http_client=http_client,
        db_conn=conn,
    )
