"""
Pytest bootstrap — zorgt dat 'import core.xxx' en 'import plugins.xxx' werken
zoals in de addon zelf (die verwacht dat homeassistant-addon/ de working
directory / op sys.path staat, zie server.py en discovery.py).
"""

import os
import sys

_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ADDON_ROOT not in sys.path:
    sys.path.insert(0, _ADDON_ROOT)
