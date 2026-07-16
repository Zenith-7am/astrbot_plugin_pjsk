"""Gemini vision engine adapter."""
from __future__ import annotations

import json
from typing import Any

import httpx
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements

from adapters.vision._http import map_request_error, map_status_error
from adapters.vision._prompt import PJSK_OCR_PROMPT
from adapters.vision._shared import _DIFF_MAP, _encode_base64

GEMINI_OCR_PROMPT = PJSK_OCR_PROMPT  # Re-export for test verification


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
        body = _build_request_body(image, PJSK_OCR_PROMPT)
        headers = {"x-goog-api-key": self._api_key.reveal()}
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._model}:generateContent"
        )
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

            difficulty = _DIFF_MAP.get(parsed.get("difficulty", "").upper())
            if difficulty is None:
                raise VisionResponseError(
                    f"Unknown difficulty: {parsed.get('difficulty')}"
                )

            return OcrObservation(
                song_title=str(parsed.get("title", "")),
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
        except (KeyError, IndexError, json.JSONDecodeError,
                ValueError, TypeError, AttributeError) as e:
            raise VisionResponseError(
                f"Cannot parse Gemini response: {e}"
            ) from e


def _build_request_body(image: bytes, prompt: str) -> dict[str, Any]:
    """Build the Gemini API request body with JSON response mode.

    Extracted as a package-private function for testability.  The
    ``responseMimeType`` and ``responseSchema`` force the model to
    output valid JSON matching the schema — no markdown wrapping,
    no extra commentary.  This is the same pattern validated in
    the old emu-bot codebase.
    """
    return {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {
                    "mimeType": "image/jpeg",
                    "data": _encode_base64(image),
                }},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "difficulty": {"type": "STRING"},
                    "level": {"type": "INTEGER"},
                    "perfect": {"type": "INTEGER"},
                    "great": {"type": "INTEGER"},
                    "good": {"type": "INTEGER"},
                    "bad": {"type": "INTEGER"},
                    "miss": {"type": "INTEGER"},
                },
                "required": [
                    "title", "difficulty", "level",
                    "perfect", "great", "good", "bad", "miss",
                ],
            },
        },
    }
