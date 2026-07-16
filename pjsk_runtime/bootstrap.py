"""Platform-agnostic Composition Root."""
from __future__ import annotations

from dataclasses import dataclass

from pjsk_core.ports.cache import CandidateStore
from pjsk_core.ports.ocr_runs import OcrRunRepository
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    SongRepository,
    UserRepository,
)


@dataclass
class AdapterBundle:
    """Collection of adapters passed to the composition root.

    Callers SHOULD use one of the pre-built bundles (production, test-account,
    shadow) rather than constructing AdapterBundle manually.
    """

    user_repo: UserRepository
    chart_repo: ChartRepository
    score_repo: ScoreRepository
    song_repo: SongRepository
    ocr_run_repo: OcrRunRepository
    candidate_store: CandidateStore
