"""Tests voor de pure configuratielogica in server.py."""

import json

import pytest

import server


def test_load_options_reads_options_file(tmp_path, monkeypatch):
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({"ha_token": "abc", "sandbox_enabled": True}))
    monkeypatch.setattr(server, "OPTIONS_FILE", str(options_file))

    options = server.load_options()
    assert options == {"ha_token": "abc", "sandbox_enabled": True}


def test_load_options_falls_back_to_env_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OPTIONS_FILE", str(tmp_path / "does_not_exist.json"))
    monkeypatch.setenv("HA_TOKEN", "env-token")

    options = server.load_options()
    assert options["ha_token"] == "env-token"


def test_resolve_secret_path_returns_custom_path_unchanged(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    path = server.resolve_secret_path({"mcp_secret_path": "/mcp-mijn-geheim"}, 9584)
    assert path == "/mcp-mijn-geheim"


def test_resolve_secret_path_adds_leading_slash(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    path = server.resolve_secret_path({"mcp_secret_path": "mcp-mijn-geheim"}, 9584)
    assert path == "/mcp-mijn-geheim"


@pytest.mark.parametrize("configured", ["", "/mcp", "mcp"])
def test_resolve_secret_path_rejects_insecure_default_and_exits(configured, monkeypatch):
    """Lege of het oude onveilige '/mcp'-pad mag nooit gebruikt worden —
    de addon genereert een nieuw pad en stopt zodat de gebruiker het overneemt."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        server.resolve_secret_path({"mcp_secret_path": configured}, 9584)
    assert exc_info.value.code == 0
