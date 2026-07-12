"""StepFun (阶跃星辰) vision engine adapter.

Uses an OpenAI-compatible chat completions endpoint.
"""
from __future__ import annotations

import base64 as _base64
import json
from typing import Any

import httpx

from adapters.vision._http import map_request_error, map_status_error
from adapters.vision.gemini import Secret
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements


_DIFF_MAP: dict[str, Difficulty] = {
    "EASY": Difficulty.EASY,
    "NORMAL": Difficulty.NORMAL,
    "HARD": Difficulty.HARD,
    "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER,
    "APPEND": Difficulty.APPEND,
}


class StepFunVisionEngine:
    """StepFun (阶跃星辰) vision engine for PJSK score screenshot recognition.

    Uses an OpenAI-compatible chat completions endpoint.

    Args:
        api_key: StepFun API key.
        model: Model name (e.g. "step-1v-32k").
        client: Shared httpx.AsyncClient instance.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._api_key = Secret(api_key)
        self._model = model
        self._client = client
        self.identity = EngineIdentity(
            engine_id=f"stepfun-{model}",
            provider="stepfun",
            model=model,
        )

    async def recognize(
        self,
        image: bytes,
        *,
        timeout: float,
    ) -> OcrObservation:
        """Recognise a PJSK score screenshot using StepFun vision.

        Args:
            image: Raw image bytes to analyse.
            timeout: Maximum request duration.

        Returns:
            Parsed OcrObservation from the StepFun response.

        Raises:
            VisionTimeoutError: Request timed out.
            VisionConnectionError: Network connection failed.
            VisionRateLimitError: API returned HTTP 429.
            VisionServerError: API returned HTTP 5xx.
            VisionResponseError: Unexpected response format or content.
        """
        prompt = (
            "You are a PJSK score screenshot reader. "
            "Extract: song title, difficulty (EASY/NORMAL/HARD/EXPERT/MASTER/APPEND), "
            "level number, and counts: PERFECT GREAT GOOD BAD MISS. "
            "Return ONLY valid JSON with keys: song_title, difficulty, level, "
            "perfect, great, good, bad, miss."
        )
        body = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{_encode_base64(image)}",
                    }},
                ],
            }],
        }
        headers = {"Authorization": f"Bearer {self._api_key.reveal()}"}
        url = "https://api.stepfun.com/v1/chat/completions"

        try:
            response = await self._client.post(
                url, json=body, headers=headers, timeout=timeout,
            )
        except httpx.RequestError as e:
            raise map_request_error(e) from e

        if response.status_code >= 400:
            raise map_status_error(response)

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Invalid JSON response: {e}") from e

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> OcrObservation:
        try:
            text = data["choices"][0]["message"]["content"]
            parsed = json.loads(text)

            difficulty = _DIFF_MAP.get(parsed.get("difficulty", "").upper())
            if difficulty is None:
                raise VisionResponseError(
                    f"Unknown difficulty: {parsed.get('difficulty')}"
                )

            return OcrObservation(
                song_title=str(parsed.get("song_title", "")),
                difficulty=difficulty,
                displayed_level=int(parsed.get("level", 0)),
                judgements=Judgements(
                    perfect=int(parsed.get("perfect", 0)),
                    great=int(parsed.get("great", 0)),
                    good=int(parsed.get("good", 0)),
                    bad=int(parsed.get("bad", 0)),
                    miss=int(parsed.get("miss", 0)),
                ),
                engine=f"stepfun-{self._model}",
                elapsed_ms=0,
            )
        except (KeyError, IndexError, json.JSONDecodeError,
                ValueError, TypeError, AttributeError) as e:
            raise VisionResponseError(
                f"Cannot parse StepFun response: {e}"
            ) from e


def _encode_base64(data: bytes) -> str:
    return _base64.b64encode(data).decode("ascii")
