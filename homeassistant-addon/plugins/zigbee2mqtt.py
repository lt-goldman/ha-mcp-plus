"""
Zigbee2MQTT plugin — list devices/groups, get device info, control devices.

Auto-discovered when the Zigbee2MQTT HA addon is running.
Uses the Z2M REST API on port 8099 (frontend/ingress port in HA addon).

Optional: set z2m_token in addon options if Z2M auth is enabled.
"""

import httpx
import logging
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.zigbee2mqtt")


class Zigbee2MQTTPlugin(BasePlugin):
    NAME          = "Zigbee2MQTT"
    DESCRIPTION   = "List and control Zigbee devices and groups via Z2M REST API"
    ADDON_SLUG    = "zigbee2mqtt"
    INTERNAL_PORT = 8099
    CONFIG_KEY    = "z2m_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url   = cfg.url.rstrip("/")
        token = cfg.token  # optional — only needed if Z2M auth is enabled

        def _headers() -> dict:
            h = {"Content-Type": "application/json"}
            if token:
                h["Authorization"] = f"Bearer {token}"
            return h

        def _get(path: str) -> dict | list:
            try:
                r = httpx.get(f"{url}/api{path}", headers=_headers(), timeout=10)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return r.json()
            except httpx.ConnectError:
                return {"error": f"Cannot connect to Zigbee2MQTT at {url}"}
            except Exception as e:
                return {"error": str(e)}

        def _post(path: str, data: dict = None) -> dict:
            try:
                r = httpx.post(f"{url}/api{path}", headers=_headers(), json=data or {}, timeout=10)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return r.json() if r.text.strip() else {"ok": True}
            except Exception as e:
                return {"error": str(e)}

        # ── BRIDGE ────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_health() -> dict:
            """Check Zigbee2MQTT connectivity and version."""
            result = _get("/health")
            if isinstance(result, dict) and "error" not in result:
                return result
            # Fallback: try bridge info
            info = _get("/bridge/info")
            if isinstance(info, dict) and "error" not in info:
                return {
                    "connected": True,
                    "version": info.get("version"),
                    "coordinator": info.get("coordinator", {}).get("type"),
                }
            return result

        @mcp.tool()
        def z2m_bridge_info() -> dict:
            """
            Get Zigbee2MQTT bridge info: coordinator type, firmware, channel,
            network settings, and Z2M version.
            """
            return _get("/bridge/info")

        @mcp.tool()
        def z2m_bridge_config() -> dict:
            """Get the full Zigbee2MQTT configuration."""
            return _get("/bridge/config")

        # ── DEVICES ───────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_list_devices(type_filter: str = "") -> dict:
            """
            List all Zigbee devices known to Z2M.

            Args:
                type_filter: Filter by device type: 'EndDevice', 'Router', or 'Coordinator'.
                             Empty = all.
            """
            devices = _get("/devices")
            if isinstance(devices, dict) and "error" in devices:
                return devices
            if not isinstance(devices, list):
                return {"error": f"Unexpected response format: {type(devices).__name__}"}
            if type_filter:
                devices = [d for d in devices if d.get("type") == type_filter]
            return {
                "count": len(devices),
                "devices": [
                    {
                        "friendly_name": d.get("friendly_name"),
                        "ieee_address": d.get("ieee_address"),
                        "type": d.get("type"),
                        "vendor": d.get("definition", {}).get("vendor") if d.get("definition") else None,
                        "model": d.get("definition", {}).get("model") if d.get("definition") else None,
                        "description": d.get("definition", {}).get("description") if d.get("definition") else None,
                        "supported": d.get("supported", False),
                        "interview_completed": d.get("interview_completed", False),
                        "disabled": d.get("disabled", False),
                    }
                    for d in devices
                    if d.get("type") != "Coordinator"  # exclude coordinator from device list
                ],
            }

        @mcp.tool()
        def z2m_get_device(friendly_name: str) -> dict:
            """
            Get detailed info for a specific Zigbee device.

            Args:
                friendly_name: Device friendly name (e.g. 'lamp_woonkamer') or IEEE address.
            """
            result = _get(f"/devices/{friendly_name}")
            if isinstance(result, dict) and "error" not in result:
                # Include exposed features if available
                definition = result.get("definition") or {}
                return {
                    "friendly_name": result.get("friendly_name"),
                    "ieee_address": result.get("ieee_address"),
                    "type": result.get("type"),
                    "vendor": definition.get("vendor"),
                    "model": definition.get("model"),
                    "description": definition.get("description"),
                    "supported": result.get("supported"),
                    "interview_completed": result.get("interview_completed"),
                    "power_source": result.get("power_source"),
                    "disabled": result.get("disabled", False),
                    "exposes": [
                        f.get("name") or f.get("type")
                        for f in definition.get("exposes", [])
                        if isinstance(f, dict)
                    ],
                    "options": definition.get("options", []),
                }
            return result

        @mcp.tool()
        def z2m_device_set(friendly_name: str, payload: dict) -> dict:
            """
            Send a command to a Zigbee device (equivalent to MQTT publish to zigbee2mqtt/{name}/set).

            Args:
                friendly_name: Device friendly name.
                payload:       Command payload, e.g. {'state': 'ON'} or
                               {'brightness': 128, 'color_temp': 300}.
            """
            return _post(f"/devices/{friendly_name}/set", payload)

        @mcp.tool()
        def z2m_device_get(friendly_name: str, payload: dict = None) -> dict:
            """
            Request current state from a Zigbee device.

            Args:
                friendly_name: Device friendly name.
                payload:       Optional: which properties to request,
                               e.g. {'state': ''} to request the state.
                               Empty = request all.
            """
            return _post(f"/devices/{friendly_name}/get", payload or {})

        @mcp.tool()
        def z2m_rename_device(friendly_name: str, new_name: str) -> dict:
            """
            Rename a Zigbee device.

            Args:
                friendly_name: Current friendly name.
                new_name:      New friendly name.
            """
            return _post(f"/devices/{friendly_name}/settings", {"friendly_name": new_name})

        # ── GROUPS ────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_list_groups() -> dict:
            """List all Zigbee groups with their members."""
            groups = _get("/groups")
            if isinstance(groups, dict) and "error" in groups:
                return groups
            if not isinstance(groups, list):
                return {"error": f"Unexpected response format: {type(groups).__name__}"}
            return {
                "count": len(groups),
                "groups": [
                    {
                        "id": g.get("id"),
                        "friendly_name": g.get("friendly_name"),
                        "members": [
                            m.get("friendly_name") or m.get("ieee_address")
                            for m in g.get("members", [])
                        ],
                    }
                    for g in groups
                ],
            }

        @mcp.tool()
        def z2m_group_set(friendly_name: str, payload: dict) -> dict:
            """
            Send a command to a Zigbee group.

            Args:
                friendly_name: Group friendly name.
                payload:       Command payload, e.g. {'state': 'OFF'}.
            """
            return _post(f"/groups/{friendly_name}/set", payload)

        log.info("[Zigbee2MQTT] Tools registered")
