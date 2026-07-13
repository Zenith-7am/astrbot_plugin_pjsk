"""PJSK AstrBot plugin entry point.

This plugin provides score screenshot OCR, personal best tracking,
B20 ranking, and chart difficulty rankings for Project SEKAI.

The real plugin implementation lives in ``plugin/main.py``.
This file is the AstrBot discovery entry point — it re-exports
``PjskPlugin`` so AstrBot's plugin scanner finds the ``@register``
decorated class.
"""

import sys
from pathlib import Path

# Ensure the plugin's own root directory is first on sys.path so that
# ``from plugin.main import PjskPlugin`` resolves to the bundled
# ``plugin/`` sub-package and not a namesake elsewhere in the Python
# environment.
_plugin_root = str(Path(__file__).resolve().parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

from plugin.main import PjskPlugin  # noqa: E402, F401 — re-export for AstrBot discovery
