"""StepFun (阶跃星辰) vision engine adapter.

Uses an OpenAI-compatible chat completions endpoint.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from adapters.vision._http import map_request_error, map_status_error
from adapters.vision._prompt import PJSK_OCR_PROMPT
from adapters.vision._shared import _encode_base64, _parse_ocr_json
from adapters.vision.gemini import Secret
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)

STEPFUN_OCR_PROMPT = PJSK_OCR_PROMPT  # Re-export for test verification


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
        prompt = PJSK_OCR_PROMPT
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
        except (KeyError, IndexError, TypeError) as e:
            raise VisionResponseError(
                f"Cannot parse StepFun response: {e}"
            ) from e

        return _parse_ocr_json(text, self.identity.engine_id)
