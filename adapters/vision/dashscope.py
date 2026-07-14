"""DashScope (阿里云百炼) vision engine adapter — Qwen3-VL family.

Uses the OpenAI-compatible chat completions endpoint on DashScope's
Beijing region.  Images are sent as Base64 Data URLs.

Endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from adapters.vision._http import map_request_error, map_status_error
from adapters.vision._prompt import PJSK_OCR_PROMPT
from adapters.vision._shared import _DIFF_MAP, _encode_base64, _extract_json
from adapters.vision.gemini import Secret
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements

DASHSCOPE_OCR_PROMPT = PJSK_OCR_PROMPT  # Re-export for test verification


class DashScopeVisionEngine:
    """DashScope (阿里云百炼) vision engine for PJSK score screenshots.

    Uses the OpenAI-compatible endpoint in the Beijing region.

    Args:
        api_key: DashScope API key from
            https://dashscope.console.aliyun.com/apiKey
        model: Model name.  Default for new installs is
            ``qwen3-vl-flash`` (cost-effective vision model).
        client: Shared httpx.AsyncClient instance.
        thinking_enabled: When True, request the model's thinking
            process.  Default False — thinking adds latency and cost.
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
            engine_id=f"dashscope-{model}",
            provider="dashscope",
            model=model,
        )

    @property
    def name(self) -> str:
        return self.identity.engine_id

    async def recognize(
        self,
        image: bytes,
        *,
        timeout: float,
    ) -> OcrObservation:
        """Recognise a PJSK score screenshot using DashScope vision.

        Args:
            image: Raw image bytes to analyse.
            timeout: Maximum request duration.

        Returns:
            Parsed OcrObservation from the DashScope response.

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

        # Disable thinking by default for cost/speed
        if not self._thinking_enabled:
            body["thinking"] = {"type": "disabled"}

        headers = {"Authorization": f"Bearer {self._api_key.reveal()}"}
        url = (
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
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
        try:
            choice = data["choices"][0]
            message = choice["message"]
            # Always read ``content`` — ``reasoning_content`` (present
            # when thinking is enabled) is the model's internal chain-of-
            # thought, NOT the final structured answer.
            text = message["content"]
            json_text = _extract_json(text)
            parsed = json.loads(json_text)

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
                engine=self.identity.engine_id,
                elapsed_ms=0,
            )
        except (KeyError, IndexError, json.JSONDecodeError,
                ValueError, TypeError, AttributeError) as e:
            raise VisionResponseError(
                f"Cannot parse DashScope response: {e}"
            ) from e

