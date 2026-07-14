"""Zhipu (智谱) vision engine adapter.

Supports free-tier ``glm-4.6v-flash`` with optional thinking mode.
Older paid models (e.g. ``glm-4v-plus``) remain compatible — this adapter
does NOT drop support for them.
"""
from __future__ import annotations

import base64 as _base64
import json
import re
from typing import Any

import httpx

from adapters.vision._http import map_request_error, map_status_error
from adapters.vision._prompt import PJSK_OCR_PROMPT
from adapters.vision.gemini import Secret
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements

ZHIPU_OCR_PROMPT = PJSK_OCR_PROMPT  # Re-export for test verification

_DIFF_MAP: dict[str, Difficulty] = {
    "EASY": Difficulty.EASY,
    "NORMAL": Difficulty.NORMAL,
    "HARD": Difficulty.HARD,
    "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER,
    "APPEND": Difficulty.APPEND,
}

# Regex to extract a fenced ```json ... ``` block.  Intentionally
# non-greedy — it stops at the first closing ```, so it cannot
# accidentally span multiple code blocks or capture trailing text.
_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Return the JSON substring from *text*.

    Handles three forms produced by Zhipu models:
    1. Bare JSON: ``"text"`` starts with ``{`` after optional whitespace.
    2. Fenced JSON: `` ```json {...} ``` `` block — the fenced content
       is returned verbatim (the fences are stripped).
    3. Whitespace-only padding: leading / trailing whitespace is ignored.

    Raises :exc:`VisionResponseError` when no JSON-like content is found.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    m = _FENCED_JSON_RE.search(stripped)
    if m is not None:
        return m.group(1)
    raise VisionResponseError(
        f"Response is not bare JSON or fenced JSON. "
        f"First 200 chars: {stripped[:200]!r}"
    )


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
                f"Cannot parse Zhipu response: {e}"
            ) from e


def _encode_base64(data: bytes) -> str:
    return _base64.b64encode(data).decode("ascii")
