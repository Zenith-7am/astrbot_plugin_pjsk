"""PJSK AstrBot plugin entry point.

This plugin provides score screenshot OCR, personal best tracking,
B20 ranking, and chart difficulty rankings for Project SEKAI.

The real plugin implementation lives in ``pjsk_emubot/main.py``.
This file is the AstrBot discovery entry point — it re-exports
``PjskPlugin`` so AstrBot's plugin scanner finds the ``@register``
decorated class.
"""

from pjsk_emubot.main import PjskPlugin  # noqa: F401 — re-export for AstrBot discovery
