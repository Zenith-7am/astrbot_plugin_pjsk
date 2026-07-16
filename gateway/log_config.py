"""Logging configuration — safe to import without side effects."""
import logging


def sanitize_third_party_loggers() -> None:
    """Silence third-party loggers that leak secrets at INFO level.

    - httpx / httpcore: log full URLs including API-key query params
      and image download URLs with rkey / fileid tokens.
    - uvicorn.access: duplicates the NoneBot event stream.
    - nonebot.adapters: raw event logs include QQ numbers, image URLs,
      and file IDs at SUCCESS level.
    """
    for _noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("nonebot.adapters").setLevel(logging.WARNING)
