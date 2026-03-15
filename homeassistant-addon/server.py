"""
ha-mcp-plus — Extended Home Assistant MCP Server
MIT License

Automatically discovers installed HA addons and activates the corresponding
plugin tools. No manual configuration of URLs needed — everything is
auto-discovered from the Supervisor API.
"""

import os
import json
import logging
from mcp.server.fastmcp import FastMCP

from core.discovery import discover_and_load_plugins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("ha-mcp-plus")

# --- Read addon options ---
# When running as a HA addon, options are written to /data/options.json
OPTIONS_FILE = "/data/options.json"


def load_options() -> dict:
    if os.path.exists(OPTIONS_FILE):
        with open(OPTIONS_FILE) as f:
            return json.load(f)
    # Fallback to environment variables (for local dev)
    return {
        "influx_token":   os.environ.get("INFLUX_TOKEN", ""),
        "influx_org":     os.environ.get("INFLUX_ORG", "homeassistant"),
        "influx_bucket":  os.environ.get("INFLUX_BUCKET", "homeassistant"),
        "grafana_token":  os.environ.get("GRAFANA_TOKEN", ""),
        "nodered_token":  os.environ.get("NODERED_TOKEN", ""),
        "mcp_secret_path": os.environ.get("MCP_SECRET_PATH", "/mcp"),
    }


def main():
    options = load_options()
    port    = int(os.environ.get("MCP_PORT", "9584"))
    path    = options.get("mcp_secret_path", "/mcp")

    log.info("=" * 60)
    log.info("ha-mcp-plus starting")
    log.info(f"Endpoint: 0.0.0.0:{port}{path}")
    log.info("=" * 60)

    # Discover which addons are running and activate plugins
    active_plugins = discover_and_load_plugins(options)

    if not active_plugins:
        log.warning("No active plugins found. Is any supported addon running?")

    # Build MCP server
    plugin_list = ", ".join(active_plugins.keys()) or "none"
    mcp = FastMCP(
        "ha-mcp-plus",
        instructions=f"""
Extended Home Assistant MCP server.
Active plugins: {plugin_list}

Available tool groups:
{chr(10).join(f"- {name}: {instance.DESCRIPTION}" for name, (instance, _) in active_plugins.items())}

Always ask for user confirmation before writing files, deploying flows, or making
changes that cannot be undone.
        """.strip(),
    )

    # Register tools from each active plugin
    for name, (instance, cfg) in active_plugins.items():
        log.info(f"Registering tools: {name}")
        instance.register_tools(mcp, cfg)

    # Also register filesystem tools (always available — needs /config mount)
    try:
        from plugins.filesystem import FilesystemPlugin
        fs_plugin = FilesystemPlugin()
        fs_cfg_extra = {"config_path": "/config"}
        from core.plugin_base import PluginConfig
        fs_cfg = PluginConfig(url="", token="", extra=fs_cfg_extra)
        fs_plugin.register_tools(mcp, fs_cfg)
        log.info("Registering tools: Filesystem (always active)")
    except Exception as e:
        log.warning(f"Could not load filesystem plugin: {e}")

    log.info(f"Starting MCP server — {len(active_plugins)} plugin(s) active")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path=path)


if __name__ == "__main__":
    main()
