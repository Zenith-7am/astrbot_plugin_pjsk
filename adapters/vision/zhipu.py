"""Zhipu (智谱) vision engine adapter.

Supports free-tier ``glm-4.6v-flash`` with optional thinking mode.
Older paid models (e.g. ``glm-4v-plus``) remain compatible — this adapter
does NOT drop support for them.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from adapters.vision._http import map_request_error, map_status_error
from adapters.vision._prompt import PJSK_OCR_PROMPT
from adapters.vision._shared import _encode_base64, _extract_json, _parse_ocr_json
from adapters.vision.gemini import Secret
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)

ZHIPU_OCR_PROMPT = PJSK_OCR_PROMPT  # Re-export for test verification


class ZhipuVisionEngine:
    """Zhipu (智谱) vision engine for PJSK score screenshot recognition.

    Uses an OpenAI-compatible chat completions endpoint.

    Args:
        api_key: Zhipu API key.
        model: Model name.  The default for new installs is
            ``glm-4.6v-flash`` (free).  Users migrating from older
            versions may still have ``glm-4v-plus`` (paid) in their
            config — both are supported.
        client: Shared httpx.AsyncClient instance.
        thinking_enabled: When True, request the model's thinking
            process.  Only effective for models that support it
            (e.g. ``glm-4.6v-flash``).  Default False — thinking adds
            latency and token cost.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
        *,
        thinking_enabled: bool = False,
    ) -> None:
        self._api_key = Secret(api_key)
        self._model = model
        self._client = client
        self._thinking_enabled = thinking_enabled
        self.identity = EngineIdentity(
            engine_id=f"zhipu-{model}",
            provider="zhipu",
            model=model,
        )

    @property
    def name(self) -> str:
        """Short name for logging / startup messages."""
        return self.identity.engine_id

    async def recognize(
        self,
        image: bytes,
        *,
        timeout: float,
    ) -> OcrObservation:
        """Recognise a PJSK score screenshot using Zhipu vision.

        Args:
            image: Raw image bytes to analyse.
            timeout: Maximum request duration.

        Returns:
            Parsed OcrObservation from the Zhipu response.

        Raises:
            VisionTimeoutError: Request timed out.
            VisionConnectionError: Network connection failed.
            VisionRateLimitError: API returned HTTP 429.
            VisionServerError: API returned HTTP 5xx.
            VisionResponseError: Unexpected response format or content.
        """
        prompt = PJSK_OCR_PROMPT
        body: dict[str, Any] = {
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

        if self._thinking_enabled:
            body["thinking"] = {"type": "enabled"}
        else:
            body["thinking"] = {"type": "disabled"}

        headers = {"Authorization": f"Bearer {self._api_key.reveal()}"}
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

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
            choice = data["choices"][0]
            message = choice["message"]
            # Always read ``content`` — ``reasoning_content`` (present
            # when thinking is enabled) is the model's internal chain-of-
            # thought, NOT the final structured answer.
            text = message["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise VisionResponseError(
                f"Cannot parse Zhipu response: {e}"
            ) from e

        json_text = _extract_json(text)
        return _parse_ocr_json(json_text, self.identity.engine_id)

