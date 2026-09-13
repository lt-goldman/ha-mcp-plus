"""
Smoke test: elke plugin-module moet importeerbaar zijn tegen de gepinde
requirements.txt.

Dit is precies de test die de v0.8.0-bug had gevangen: websocket-client werd
gebruikt (import websocket in core/websocket.py en plugins/musicassistant.py)
maar stond niet in requirements.txt. Bij een schone install crashte
plugins/musicassistant.py bij het importeren, wat load_all_plugins()
meesleurde (voor deze fix) en zo de hele addon liet crashen voor iedereen,
niet alleen voor Music Assistant-gebruikers.
"""

import importlib
import pkgutil

import pytest

import plugins as plugins_pkg


def _plugin_module_names():
    return [name for _, name, _ in pkgutil.iter_modules(plugins_pkg.__path__)]


@pytest.mark.parametrize("module_name", _plugin_module_names())
def test_plugin_module_imports_cleanly(module_name):
    """Elke plugins/<naam>.py moet los te importeren zijn — geen ontbrekende
    dependency, geen syntaxfout, geen top-level code die crasht."""
    importlib.import_module(f"plugins.{module_name}")


def test_core_modules_import_cleanly():
    import core.discovery       # noqa: F401
    import core.plugin_base     # noqa: F401
    import core.safety          # noqa: F401
    import core.websocket       # noqa: F401  <- gebruikt websocket-client


def test_server_module_imports_cleanly():
    # Vereist o.a. fastmcp en uvicorn — moet exact matchen met requirements.txt.
    import server  # noqa: F401
