"""Gemini vision engine adapter."""
from __future__ import annotations

import base64 as _base64
import json
from typing import Any

import httpx
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements

from adapters.vision._http import map_request_error, map_status_error


class Secret:
    """Wraps a secret value that should not leak in repr()."""

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"


class GeminiVisionEngine:
    """Gemini API vision engine for PJSK score screenshot recognition.

    Args:
        api_key: Google Gemini API key.
        model: Gemini model name (e.g. "gemini-2.5-flash").
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
            engine_id=f"gemini-{model}",
            provider="google",
            model=model,
        )

    async def recognize(
        self,
        image: bytes,
        *,
        timeout: float,
    ) -> OcrObservation:
        """Recognise a PJSK score screenshot using Gemini vision.

        Args:
            image: Raw image bytes to analyse.
            timeout: Maximum request duration.

        Returns:
            Parsed OcrObservation from the Gemini response.

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
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": "image/jpeg",
                        "data": _encode_base64(image),
                    }},
                ]
            }],
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._model}:generateContent"
            f"?key={self._api_key.reveal()}"
        )
        try:
            response = await self._client.post(url, json=body, timeout=timeout)
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
        """Parse the Gemini API response into an OcrObservation.

        Args:
            data: Parsed JSON body from the Gemini response.

        Returns:
            An OcrObservation with the extracted fields.

        Raises:
            VisionResponseError: If the response structure is unexpected
                or the difficulty string is unknown.
        """
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise VisionResponseError(
                f"Cannot parse Gemini response: {e}"
            ) from e

        diff_map: dict[str, Difficulty] = {
            "EASY": Difficulty.EASY,
            "NORMAL": Difficulty.NORMAL,
            "HARD": Difficulty.HARD,
            "EXPERT": Difficulty.EXPERT,
            "MASTER": Difficulty.MASTER,
            "APPEND": Difficulty.APPEND,
        }
        difficulty = diff_map.get(parsed.get("difficulty", "").upper())
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
            engine=f"gemini-{self._model}",
            elapsed_ms=0,
        )


def _encode_base64(data: bytes) -> str:
    return _base64.b64encode(data).decode("ascii")
