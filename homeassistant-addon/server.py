"""
ha-mcp-plus — Extended Home Assistant MCP Server
MIT License

Automatically discovers installed HA addons and activates the corresponding
plugin tools. No manual configuration of URLs needed — everything is
auto-discovered from the Supervisor API.
"""

import ipaddress
import json
import logging
import os
import socket
import uuid

import uvicorn
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

import importlib.metadata
try:
    _mcp_version = importlib.metadata.version("mcp")
except Exception:
    _mcp_version = "unknown"

import httpx

from core.discovery import discover_and_load_plugins
from core.plugin_base import PluginConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("ha-mcp-plus")

OPTIONS_FILE       = "/data/options.json"
GENERATED_PATH_FILE = "/data/generated_mcp_path.txt"


# ── Options ───────────────────────────────────────────────────

def load_options() -> dict:
    if os.path.exists(OPTIONS_FILE):
        log.info(f"Loading options from {OPTIONS_FILE}")
        with open(OPTIONS_FILE) as f:
            return json.load(f)
    log.warning("Options file not found — falling back to environment variables (local dev mode)")
    return {
        "ha_token":         os.environ.get("HA_TOKEN", ""),
        "influx_token":     os.environ.get("INFLUX_TOKEN", ""),
        "influx_org":       os.environ.get("INFLUX_ORG", "homeassistant"),
        "influx_bucket":    os.environ.get("INFLUX_BUCKET", "homeassistant"),
        "grafana_token":    os.environ.get("GRAFANA_TOKEN", ""),
        "nodered_token":    os.environ.get("NODERED_TOKEN", ""),
        "mcp_secret_path":  os.environ.get("MCP_SECRET_PATH", ""),
        "allowed_networks": os.environ.get("ALLOWED_NETWORKS", ""),
        "sandbox_enabled":  os.environ.get("SANDBOX_ENABLED", "false").lower() == "true",
    }


def _inject_ha_token(options: dict) -> None:
    ha_token = options.get("ha_token", "").strip()
    if ha_token:
        os.environ["HA_REST_TOKEN"] = ha_token
        log.info("Using ha_token from addon options for Home Assistant authentication")


# ── Secret path ───────────────────────────────────────────────

def _notify_endpoint(path: str, port: int) -> None:
    """Post a persistent HA notification with the active MCP endpoint."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return
    try:
        httpx.post(
            "http://supervisor/core/api/services/persistent_notification/create",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "notification_id": "ha_mcp_plus_endpoint",
                "title": "HA MCP Plus — actief endpoint",
                "message": (
                    f"Het MCP server pad is:\n\n"
                    f"**Pad:** `{path}`\n"
                    f"**Poort:** `{port}`\n\n"
                    f"Gebruik dit pad in je Claude / MCP client configuratie."
                ),
            },
            timeout=5,
        )
        log.info(f"[Security] Endpoint notification posted to HA UI")
    except Exception as e:
        log.warning(f"Could not post HA notification: {e}")


def _write_path_to_addon_options(path: str) -> None:
    """Write the generated path back to addon options via Supervisor API.
    This makes it visible in the Configuration tab on the addon info page."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return
    try:
        # Read current options
        r = httpx.get(
            "http://supervisor/addons/self/options/config",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if r.status_code != 200:
            return
        current = r.json().get("data", {})
        # Only write back if path differs to avoid unnecessary restarts
        if current.get("mcp_secret_path", "") == path:
            return
        current["mcp_secret_path"] = path
        httpx.post(
            "http://supervisor/addons/self/options",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"options": current},
            timeout=5,
        )
        log.info(f"[Security] Active MCP path written to addon Configuration tab")
    except Exception as e:
        log.warning(f"Could not write path to addon options: {e}")


def resolve_secret_path(options: dict) -> str:
    """
    Return the MCP secret path.
    - If configured and not the old default '/mcp': use as-is.
    - Otherwise: generate a UUID-based path once, persist it, and
      write it back to the addon options (visible in Configuration tab).
    """
    configured = options.get("mcp_secret_path", "").strip()
    if configured and configured != "/mcp":
        return configured if configured.startswith("/") else f"/{configured}"

    # Use or generate a persistent random path
    if os.path.exists(GENERATED_PATH_FILE):
        with open(GENERATED_PATH_FILE) as f:
            path = f.read().strip()
        if path:
            _write_path_to_addon_options(path)
            return path

    path = f"/mcp-{uuid.uuid4().hex[:16]}"
    try:
        with open(GENERATED_PATH_FILE, "w") as f:
            f.write(path)
    except Exception as e:
        log.warning(f"Could not persist generated path: {e}")
    _write_path_to_addon_options(path)
    return path


# ── Network / IP filtering ────────────────────────────────────

def _local_subnet() -> str:
    """Best-effort: detect the local machine's /24 subnet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return str(ipaddress.IPv4Network(f"{ip}/24", strict=False))
    except Exception:
        return "192.168.0.0/16"


def resolve_allowed_networks(options: dict) -> list[ipaddress.IPv4Network]:
    """
    Parse allowed_networks from config (comma-separated CIDRs).
    Falls back to auto-detected local /24 subnet + loopback.
    """
    raw = options.get("allowed_networks", "").strip()
    cidrs = [c.strip() for c in raw.split(",") if c.strip()] if raw else []

    if not cidrs:
        auto = _local_subnet()
        cidrs = [auto]
        log.info(f"[Security] allowed_networks not set — auto-detected subnet: {auto}")

    networks = []
    for cidr in cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            log.warning(f"[Security] Invalid CIDR '{cidr}' in allowed_networks — skipping")

    # Always allow loopback
    networks.append(ipaddress.ip_network("127.0.0.0/8"))
    return networks


class IPFilterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_networks: list):
        super().__init__(app)
        self.allowed = allowed_networks

    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        try:
            addr = ipaddress.ip_address(client_ip)
            if any(addr in net for net in self.allowed):
                return await call_next(request)
        except ValueError:
            pass
        log.warning(f"[Security] Blocked connection from {client_ip}")
        return PlainTextResponse("403 Forbidden", status_code=403)


# ── Main ──────────────────────────────────────────────────────

def main():
    options = load_options()
    _inject_ha_token(options)

    port    = int(os.environ.get("MCP_PORT", "9584"))
    path    = resolve_secret_path(options)
    networks = resolve_allowed_networks(options)
    sandbox_enabled = bool(options.get("sandbox_enabled", False))

    _notify_endpoint(path, port)

    log.info("=" * 60)
    log.info("ha-mcp-plus starting")
    log.info(f"MCP SDK version: {_mcp_version}")
    log.info(f"Endpoint:        0.0.0.0:{port}{path}")
    log.info(f"Sandbox:         {'ENABLED' if sandbox_enabled else 'disabled'}")
    log.info(f"Allowed networks: {', '.join(str(n) for n in networks)}")
    log.info("=" * 60)

    # Discover which addons are running and activate plugins
    active_plugins = discover_and_load_plugins(options)
    if not active_plugins:
        log.warning("No active plugins found. Is any supported addon running?")

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

    # Filesystem tools (always active)
    try:
        from plugins.filesystem import FilesystemPlugin
        fs_plugin = FilesystemPlugin()
        fs_cfg = PluginConfig(url="", token="", extra={"config_path": "/config"})
        fs_plugin.register_tools(mcp, fs_cfg)
        log.info("Registering tools: Filesystem (always active)")
    except Exception as e:
        log.warning(f"Could not load filesystem plugin: {e}")

    # Core HA tools (always active)
    try:
        from plugins.homeassistant import HomeAssistantPlugin
        ha_plugin = HomeAssistantPlugin()
        ha_cfg = PluginConfig(url="", token="", extra=options)
        ha_plugin.register_tools(mcp, ha_cfg)
        log.info("Registering tools: HomeAssistant (always active)")
    except Exception as e:
        log.warning(f"Could not load homeassistant plugin: {e}")

    # Python sandbox (only when explicitly enabled)
    if sandbox_enabled:
        try:
            from plugins.sandbox import SandboxPlugin
            sandbox_plugin = SandboxPlugin()
            influx_url = ""
            if "InfluxDB" in active_plugins:
                _, influx_cfg = active_plugins["InfluxDB"]
                influx_url = influx_cfg.url
            sandbox_cfg = PluginConfig(url="", token="", extra={**options, "_influx_url": influx_url})
            sandbox_plugin.register_tools(mcp, sandbox_cfg)
            log.info("Registering tools: Sandbox (enabled)")
        except Exception as e:
            log.warning(f"Could not load sandbox plugin: {e}")
    else:
        log.info("Sandbox disabled (set sandbox_enabled: true to enable)")

    # Build ASGI app with IP filter middleware and run via uvicorn
    middleware = [Middleware(IPFilterMiddleware, allowed_networks=networks)]
    try:
        app = mcp.http_app(path=path, middleware=middleware)
    except TypeError:
        # Older FastMCP without middleware param — add it after
        app = mcp.http_app(path=path)
        app.add_middleware(IPFilterMiddleware, allowed_networks=networks)

    log.info(f"Starting MCP server — {len(active_plugins)} plugin(s) active")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
