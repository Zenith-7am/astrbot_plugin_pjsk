"""Shared HTTP error mapping for vendor vision adapters."""
from __future__ import annotations

import httpx
from pjsk_core.domain.ocr import (
    VisionConnectionError,
    VisionRateLimitError,
    VisionResponseError,
    VisionServerError,
    VisionTimeoutError,
)


def map_request_error(error: httpx.RequestError) -> VisionConnectionError | VisionTimeoutError:
    """Map transport-layer errors.

    Args:
        error: An httpx transport error (connection, timeout, etc.).

    Returns:
        VisionTimeoutError for timeouts, VisionConnectionError for all others.
    """
    if isinstance(error, httpx.TimeoutException):
        return VisionTimeoutError(str(error))
    return VisionConnectionError(str(error))


def map_status_error(response: httpx.Response) -> VisionRateLimitError | VisionServerError | VisionResponseError:
    """Map HTTP status errors (call AFTER receiving a response).

    Args:
        response: The httpx Response with a non-2xx status code.

    Returns:
        VisionRateLimitError for HTTP 429,
        VisionServerError for HTTP 5xx,
        VisionResponseError for all other client errors.
    """
    status = response.status_code
    if status == 429:
        return VisionRateLimitError(f"HTTP 429: {response.text[:200]}")
    if 500 <= status < 600:
        return VisionServerError(f"HTTP {status}: {response.text[:200]}")
    return VisionResponseError(f"HTTP {status}: {response.text[:200]}")
