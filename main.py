"""PJSK AstrBot plugin entry point.

This plugin provides score screenshot OCR, personal best tracking,
B20 ranking, and chart difficulty rankings for Project SEKAI.

The real plugin implementation lives in ``pjsk_emubot/main.py``.
This file is the AstrBot discovery entry point — it re-exports
``PjskPlugin`` so AstrBot's plugin scanner finds the ``@register``
decorated class.

AstrBot does not always add the plugin's own directory to ``sys.path``
before importing this entry module.  We insert it explicitly so that
``from pjsk_emubot.main import …`` resolves to the bundled sub-package
regardless of how AstrBot loads the plugin.
"""

import sys
from pathlib import Path

_plugin_root = str(Path(__file__).resolve().parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

from pjsk_emubot.main import PjskPlugin  # noqa: E402, F401
