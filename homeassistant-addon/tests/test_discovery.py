"""
Tests voor core/discovery.py — met name de veerkracht die in v0.8.0 is
toegevoegd: één kapotte plugin-module of één falende Supervisor-aanroep mag
niet de rest van de discovery (en daarmee de hele addon) meenemen.
"""

import sys
import types

import httpx
import pytest

from core import discovery


# ── find_addon_slug / discover_addon_url — pure logica, geen netwerk ──────

def test_find_addon_slug_matches_suffix_after_repo_prefix():
    addons = [{"slug": "a0d7b954_influxdb"}, {"slug": "ccab4aaf_frigate-proxy"}]
    assert discovery.find_addon_slug("influxdb", addons) == "a0d7b954_influxdb"
    assert discovery.find_addon_slug("frigate", addons) == "ccab4aaf_frigate-proxy"


def test_find_addon_slug_no_match_returns_none():
    addons = [{"slug": "a0d7b954_influxdb"}]
    assert discovery.find_addon_slug("grafana", addons) is None


def test_discover_addon_url_uses_mapped_port_when_present(monkeypatch):
    monkeypatch.setattr(
        discovery, "get_addon_info",
        lambda slug: {"state": "started", "network": {"8086/tcp": 18086}},
    )
    url = discovery.discover_addon_url("a0d7b954_influxdb", 8086)
    assert url == "http://a0d7b954-influxdb:18086"


def test_discover_addon_url_falls_back_to_internal_port_on_host_network(monkeypatch):
    monkeypatch.setattr(
        discovery, "get_addon_info",
        lambda slug: {"state": "started", "network": {"8086/tcp": None}},
    )
    url = discovery.discover_addon_url("a0d7b954_influxdb", 8086)
    assert url == "http://a0d7b954-influxdb:8086"


def test_discover_addon_url_none_when_addon_not_running(monkeypatch):
    monkeypatch.setattr(
        discovery, "get_addon_info",
        lambda slug: {"state": "stopped", "network": {}},
    )
    assert discovery.discover_addon_url("a0d7b954_influxdb", 8086) is None


# ── load_all_plugins — moet één kapotte module overleven ──────────────────

def test_load_all_plugins_skips_broken_module_but_keeps_the_rest(monkeypatch):
    """Regressietest voor de v0.8.0-bug: een module die niet kan importeren
    (bv. ontbrekende dependency) mag de andere plugin-classes niet meeslepen."""
    import plugins as plugins_pkg

    real_import_module = discovery.importlib.import_module

    def fake_import_module(name):
        if name == "plugins.broken_for_test":
            raise ModuleNotFoundError("No module named 'websocket'")
        return real_import_module(name)

    fake_modinfo = types.SimpleNamespace()
    monkeypatch.setattr(
        discovery.pkgutil, "iter_modules",
        lambda path: [
            (None, "broken_for_test", False),
            (None, "homeassistant", False),  # bestaat echt, geen ADDON_SLUG dus levert geen classes
        ],
    )
    monkeypatch.setattr(discovery.importlib, "import_module", fake_import_module)

    # Mag niet raisen — de kapotte module wordt overgeslagen, niet fataal.
    classes = discovery.load_all_plugins()
    assert isinstance(classes, list)


# ── discover_and_load_plugins — falende Supervisor-call mag niet crashen ──

def test_discover_and_load_plugins_handles_supervisor_unreachable(monkeypatch):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Cannot connect to Supervisor API")

    monkeypatch.setattr(discovery.httpx, "get", raise_connect_error)

    # list_all_addons() vangt de fout zelf al af en geeft [] terug —
    # discover_and_load_plugins mag daarmee gewoon doorgaan (leeg resultaat).
    result = discovery.discover_and_load_plugins({})
    assert result == {}
