"""Manual vision-engine benchmark tool.

Compares OCR accuracy and latency across configured engines using a
local directory of anonymised (no QQ/game ID) PJSK screenshots.

**Usage** (from repo root)::

    python tools/benchmark_vision_engines.py ./test_screenshots/ --engines gemini zhipu

**Requirements:**
- API keys set via environment variables (never in config files or CLI):
  ``GEMINI_API_KEY``, ``ZHIPU_API_KEY``, ``STEPFUN_API_KEY``,
  ``MODELSCOPE_API_KEY``.
- A ``ground_truth.json`` file in the screenshots directory mapping
  each image filename to expected fields.

**ground_truth.json format**::

    {
      "shot_001.png": {
        "song_title": "Tell Your World",
        "difficulty": "MASTER",
        "level": 30,
        "perfect": 1050, "great": 10, "good": 0, "bad": 0, "miss": 0
      }
    }

This tool does NOT run in CI/pytest by default — it requires real API
credentials and makes live HTTP calls.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

# ── Engine builder types ─────────────────────────────────────────────────


class VisionEngine(Protocol):
    """Subset of what every vision engine exposes — enough for the benchmark."""
    identity: Any  # EngineIdentity

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> Any: ...  # OcrObservation


EngineBuilder = Callable[[httpx.AsyncClient], VisionEngine]

_ENGINE_BUILDERS: dict[str, EngineBuilder] = {}


def _register(name: str) -> Callable[[EngineBuilder], EngineBuilder]:
    """Decorator that registers an engine builder under *name*."""
    def decorator(builder: EngineBuilder) -> EngineBuilder:
        _ENGINE_BUILDERS[name] = builder
        return builder
    return decorator


@_register("gemini")
def _build_gemini(client: httpx.AsyncClient) -> VisionEngine:
    from adapters.vision.gemini import GeminiVisionEngine
    return GeminiVisionEngine(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.environ.get("GEMINI_MODEL", "2.5-flash"),
        client=client,
    )


@_register("zhipu")
def _build_zhipu(client: httpx.AsyncClient) -> VisionEngine:
    from adapters.vision.zhipu import ZhipuVisionEngine
    return ZhipuVisionEngine(        api_key=os.environ["ZHIPU_API_KEY"],
        model=os.environ.get("ZHIPU_MODEL", "glm-4.6v-flash"),
        client=client,
        thinking_enabled=os.environ.get("ZHIPU_THINKING", "") == "1",
    )


@_register("stepfun")
def _build_stepfun(client: httpx.AsyncClient) -> VisionEngine:
    from adapters.vision.stepfun import StepFunVisionEngine
    return StepFunVisionEngine(        api_key=os.environ["STEPFUN_API_KEY"],
        model=os.environ.get("STEPFUN_MODEL", "step-1v-32k"),
        client=client,
    )


@_register("modelscope")
def _build_modelscope(client: httpx.AsyncClient) -> VisionEngine:
    from adapters.vision.modelscope import ModelScopeVisionEngine
    return ModelScopeVisionEngine(        api_key=os.environ["MODELSCOPE_API_KEY"],
        model=os.environ.get("MODELSCOPE_MODEL", "Qwen/QVQ-72B-Preview"),
        client=client,
    )


# ── Data types ────────────────────────────────────────────────────────────


@dataclass
class SingleResult:
    engine: str
    image: str
    elapsed_ms: int
    song_ok: bool
    difficulty_ok: bool
    judgements_ok: bool  # all 5 match
    error: str | None = None


@dataclass
class EngineReport:
    engine: str
    total: int = 0
    song_correct: int = 0
    diff_correct: int = 0
    all_judgements_correct: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    timeouts: int = 0
    rate_limits: int = 0
    server_errors: int = 0
    other_errors: int = 0

    @property
    def p50_ms(self) -> float:
        return _percentile(self.latencies_ms, 50)

    @property
    def p95_ms(self) -> float:
        return _percentile(self.latencies_ms, 95)

    def summary(self) -> str:
        if self.total == 0:
            return f"{self.engine}: 0 samples"
        return (
            f"{self.engine}: {self.total} samples | "
            f"song={self.song_correct}/{self.total} "
            f"diff={self.diff_correct}/{self.total} "
            f"all5={self.all_judgements_correct}/{self.total} | "
            f"P50={self.p50_ms:.0f}ms P95={self.p95_ms:.0f}ms | "
            f"to={self.timeouts} rl={self.rate_limits} "
            f"srv={self.server_errors} err={self.other_errors}"
        )


def _percentile(data: list[int], pct: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] * (1 - c) + sorted_data[f + 1] * c
    return float(sorted_data[f])


# ── Truth loading ──────────────────────────────────────────────────────────

_TRUTH_REQUIRED_KEYS = frozenset({
    "song_title", "difficulty", "level", "perfect",
    "great", "good", "bad", "miss",
})


def _load_truth(truth_path: Path) -> dict[str, dict[str, object]]:
    """Load and validate ground_truth.json.

    Returns ``{filename: {song_title, difficulty, level, perfect, …}}``.
    Raises ``ValueError`` when the top-level value is not a dict of dicts
    or when any entry is missing required keys.
    """
    with open(truth_path, encoding="utf-8") as f:
        raw: Any = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError(
            f"ground_truth.json must be a JSON object mapping filenames "
            f"to entries, got {type(raw).__name__}"
        )

    result: dict[str, dict[str, object]] = {}
    for filename, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"ground_truth.json[{filename!r}] must be a JSON object, "
                f"got {type(entry).__name__}"
            )
        missing = _TRUTH_REQUIRED_KEYS - entry.keys()
        if missing:
            raise ValueError(
                f"ground_truth.json[{filename!r}] missing keys: {sorted(missing)}"
            )
        result[str(filename)] = dict(entry)
    return result


# ── Main logic ────────────────────────────────────────────────────────────


async def _run_one(
    engine: VisionEngine,
    image_path: Path,
    truth: dict[str, object],
    timeout: float,
) -> SingleResult:
    image_bytes = image_path.read_bytes()
    t0 = time.monotonic()
    try:
        obs = await engine.recognize(image_bytes, timeout=timeout)
    except Exception as exc:
        cls = type(exc).__name__
        return SingleResult(
            engine=engine.identity.engine_id,
            image=image_path.name,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            song_ok=False, difficulty_ok=False, judgements_ok=False,
            error=cls,
        )
    elapsed = int((time.monotonic() - t0) * 1000)
    return SingleResult(
        engine=engine.identity.engine_id,
        image=image_path.name,
        elapsed_ms=elapsed,
        song_ok=obs.song_title.lower() == str(truth["song_title"]).lower(),
        difficulty_ok=obs.difficulty.value == str(truth["difficulty"]),
        judgements_ok=(
            obs.judgements.perfect == int(str(truth["perfect"]))
            and obs.judgements.great == int(str(truth["great"]))
            and obs.judgements.good == int(str(truth["good"]))
            and obs.judgements.bad == int(str(truth["bad"]))
            and obs.judgements.miss == int(str(truth["miss"]))
        ),
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PJSK vision engines")
    parser.add_argument(
        "screenshots_dir",
        help="Directory containing anonymised screenshots + ground_truth.json",
    )
    parser.add_argument(
        "--engines", nargs="+", default=["zhipu"],
        help="Engines to test (default: zhipu)",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="Per-engine request timeout in seconds",
    )
    args = parser.parse_args()

    root = Path(args.screenshots_dir)
    truth = _load_truth(root / "ground_truth.json")

    # Collect image files (skip truth and hidden files)
    image_files = sorted(
        p for p in root.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg")
        and not p.name.startswith(".")
    )
    if not image_files:
        print(f"No images found in {root}")
        sys.exit(1)

    # Build engines
    async with httpx.AsyncClient(timeout=args.timeout + 5) as client:
        engines: list[VisionEngine] = []
        for name in args.engines:
            if name not in _ENGINE_BUILDERS:
                print(f"Unknown engine: {name}.  Choices: {sorted(_ENGINE_BUILDERS)}")
                sys.exit(1)
            env_key = f"{name.upper()}_API_KEY"
            if env_key not in os.environ:
                print(f"Skip {name}: {env_key} not set")
                continue
            engines.append(_ENGINE_BUILDERS[name](client))

        if not engines:
            print("No engines available. Set at least one *_API_KEY env var.")
            sys.exit(1)

        print(f"Engines: {[e.identity.engine_id for e in engines]}")
        print(f"Images:  {len(image_files)}")
        print()

        # Run all engine×image combinations
        reports: dict[str, EngineReport] = {
            e.identity.engine_id: EngineReport(engine=e.identity.engine_id)
            for e in engines
        }

        for img_path in image_files:
            t = truth.get(img_path.name)
            if t is None:
                print(f"  SKIP {img_path.name} — not in ground_truth.json")
                continue
            for eng in engines:
                r = await _run_one(eng, img_path, t, args.timeout)
                rep = reports[eng.identity.engine_id]
                rep.total += 1
                if r.error:
                    err_lower = r.error.lower()
                    if "timeout" in err_lower:
                        rep.timeouts += 1
                    elif "ratelimit" in err_lower:
                        rep.rate_limits += 1
                    elif "server" in err_lower:
                        rep.server_errors += 1
                    else:
                        rep.other_errors += 1
                else:
                    if r.song_ok:
                        rep.song_correct += 1
                    if r.difficulty_ok:
                        rep.diff_correct += 1
                    if r.judgements_ok:
                        rep.all_judgements_correct += 1
                    rep.latencies_ms.append(r.elapsed_ms)

        # ── Print reports ──────────────────────────────────────────────
        for _eng_id, rep in reports.items():
            print(rep.summary())
        print()
        print("Done — benchmark complete.")
        print("Note: these results are specific to PJSK screenshots.")
        print("Do not declare a general best model from this data alone.")


if __name__ == "__main__":
    asyncio.run(main())
