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
    from fastmcp import FastMCP
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        from mcp.server.mcpserver import MCPServer as FastMCP

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

OPTIONS_FILE = "/data/options.json"


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

def _publish_path_to_ha(path: str, port: int) -> None:
    """Publish the generated path via two HA mechanisms:
    1. sensor.ha_mcp_plus_endpoint state (Developer Tools → States)
    2. persistent_notification (bell icon in HA UI)
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Set a HA sensor state — always visible in Developer Tools → States
    try:
        r = httpx.post(
            "http://supervisor/core/api/states/sensor.ha_mcp_plus_endpoint",
            headers=headers,
            json={
                "state": path,
                "attributes": {
                    "friendly_name": "HA MCP Plus — actief pad",
                    "port": port,
                    "icon": "mdi:server-network",
                    "url": f"http://jouw-ha-ip:{port}{path}",
                },
            },
            timeout=5,
        )
        if r.status_code in (200, 201):
            log.info("[Security] Path set as sensor.ha_mcp_plus_endpoint (Developer Tools → States)")
        else:
            log.warning(f"[Security] sensor state write returned {r.status_code}: {r.text}")
    except Exception as e:
        log.warning(f"Could not set sensor state: {e}")

    # 2. Persistent notification — bell icon in HA UI
    try:
        r = httpx.post(
            "http://supervisor/core/api/services/persistent_notification/create",
            headers=headers,
            json={
                "notification_id": "ha_mcp_plus_path",
                "title": "HA MCP Plus — stel je MCP pad in",
                "message": (
                    f"Jouw gegenereerde MCP pad is:\n\n"
                    f"`{path}`\n\n"
                    f"Kopieer dit naar de **Configuration tab** van de addon en herstart."
                ),
            },
            timeout=5,
        )
        if r.status_code in (200, 201):
            log.info("[Security] Persistent notification created (bel-icoon in HA)")
        else:
            log.warning(f"[Security] notification returned {r.status_code}: {r.text}")
    except Exception as e:
        log.warning(f"Could not create notification: {e}")


def _write_path_to_addon_options(path: str, options: dict) -> None:
    """Attempt to write the generated path to addon options via Supervisor API."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return
    try:
        current = dict(options)
        current["mcp_secret_path"] = path
        r = httpx.post(
            "http://supervisor/addons/self/options",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"options": current},
            timeout=5,
        )
        if r.status_code in (200, 204):
            log.info("[Security] Path written to addon Configuration tab")
        else:
            log.warning(f"[Security] options write returned {r.status_code}: {r.text}")
    except Exception as e:
        log.warning(f"Could not write path to addon options: {e}")


def resolve_secret_path(options: dict, port: int) -> str:
    """
    Return the MCP secret path.
    - If configured and not the insecure default '/mcp': use as-is.
    - If empty or '/mcp': auto-generate, write to HA system log + Configuration tab, exit.
    """
    path = options.get("mcp_secret_path", "").strip()

    if path and path not in ("/mcp", "mcp"):
        return path if path.startswith("/") else f"/{path}"

    # Path is empty or the insecure old default — auto-generate
    generated = f"/mcp-{uuid.uuid4().hex[:16]}"

    # Write to /config/ha_mcp_plus_path.txt — guaranteed via config:rw mount
    try:
        with open("/config/ha_mcp_plus_path.txt", "w") as f:
            f.write(f"HA MCP Plus — jouw MCP pad\n")
            f.write(f"=" * 40 + "\n")
            f.write(f"mcp_secret_path: {generated}\n\n")
            f.write(f"Kopieer de bovenste regel naar de Configuration tab\n")
            f.write(f"van de HA MCP Plus addon en herstart de addon.\n")
        log.info(f"[Security] Pad geschreven naar /config/ha_mcp_plus_path.txt")
    except Exception as e:
        log.warning(f"Could not write to /config: {e}")

    _publish_path_to_ha(generated, port)
    _write_path_to_addon_options(generated, options)

    log.info("=" * 60)
    log.info("[Security] NIEUW MCP PAD GEGENEREERD:")
    log.info(f"[Security]   {generated}")
    log.info("[Security] Vind dit pad in /config/ha_mcp_plus_path.txt")
    log.info("[Security] (zichtbaar via Bestandsbeheerder in HA)")
    log.info("[Security] Stel het in via Configuration tab en herstart.")
    log.info("=" * 60)

    raise SystemExit(0)


# ── Network / IP filtering ────────────────────────────────────

def _auto_detect_networks() -> list[ipaddress.IPv4Network]:
    """
    Detect all subnets the addon is connected to:
    - Loopback (always)
    - Docker/supervisor bridge network (detected via hostname resolution)
    - HA host LAN network (detected via outbound route)
    Returns deduplicated list of /24 networks.
    """
    found = set()

    # Loopback — always
    found.add("127.0.0.0/8")

    # Primary outbound interface (usually the Docker bridge or LAN)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        found.add(str(ipaddress.IPv4Network(f"{ip}/24", strict=False)))
    except Exception:
        pass

    # All IPs bound to this container (catches Docker bridge + any extra interfaces)
    try:
        for addr_info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = addr_info[4][0]
            addr = ipaddress.ip_address(ip)
            if not addr.is_loopback:
                found.add(str(ipaddress.IPv4Network(f"{ip}/24", strict=False)))
    except Exception:
        pass

    networks = []
    for cidr in found:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            pass
    return networks


def resolve_allowed_networks(options: dict) -> list[ipaddress.IPv4Network]:
    """
    Always allow: loopback + all auto-detected local subnets (Docker + LAN).
    Optionally add extra CIDRs from allowed_networks config (additive, never replaces auto).
    """
    # Base: always auto-detect
    networks = _auto_detect_networks()
    log.info(f"[Security] Auto-detected networks: {', '.join(str(n) for n in networks)}")

    # Extra: user-configured (additive)
    raw = options.get("allowed_networks", "").strip()
    if raw:
        for cidr in [c.strip() for c in raw.split(",") if c.strip()]:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
                if net not in networks:
                    networks.append(net)
                    log.info(f"[Security] Extra network allowed: {net}")
            except ValueError:
                log.warning(f"[Security] Invalid CIDR '{cidr}' in allowed_networks — skipping")

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
    path    = resolve_secret_path(options, port)
    networks = resolve_allowed_networks(options)
    sandbox_enabled = bool(options.get("sandbox_enabled", False))

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
