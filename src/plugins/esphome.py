"""
ESPHome plugin — auto-activated when 5c53de3b_esphome is running.

This is a good example of how simple it is to add a new plugin:
1. Subclass BasePlugin
2. Set ADDON_SLUG, INTERNAL_PORT, NAME
3. Implement register_tools()
That's it — discovery and loading is automatic!
"""

import httpx
from typing import Optional
from core.plugin_base import BasePlugin, PluginConfig


class ESPHomePlugin(BasePlugin):
    NAME          = "ESPHome"
    DESCRIPTION   = "Manage ESPHome devices, check logs, trigger OTA updates"
    ADDON_SLUG    = "5c53de3b_esphome"
    INTERNAL_PORT = 6052
    CONFIG_KEY    = ""  # ESPHome uses HA auth, no separate token

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url

        @mcp.tool()
        def esphome_health() -> dict:
            """Check ESPHome connectivity."""
            try:
                r = httpx.get(f"{url}/", timeout=5)
                return {"connected": r.status_code == 200}
            except Exception as e:
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def esphome_list_devices() -> dict:
            """
            List all ESPHome devices with their online/offline status.
            """
            try:
                r = httpx.get(f"{url}/devices.json", timeout=10)
                data = r.json()
                devices = data if isinstance(data, list) else data.get("devices", [])
                return {
                    "count": len(devices),
                    "devices": [
                        {
                            "name": d.get("name"),
                            "friendly_name": d.get("friendly_name"),
                            "configuration": d.get("configuration"),
                            "loaded_integrations": d.get("loaded_integrations", []),
                            "deployed_version": d.get("deployed_version"),
                            "current_version": d.get("current_version"),
                            "update_available": d.get("deployed_version") != d.get("current_version"),
                            "online": d.get("online", False),
                        }
                        for d in devices
                    ],
                }
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def esphome_get_device_logs(device_name: str) -> dict:
            """
            Get recent logs from an ESPHome device.

            Args:
                device_name: Device name (as shown in ESPHome dashboard).
            """
            try:
                r = httpx.get(f"{url}/{device_name}/logs", timeout=10)
                return {"device": device_name, "logs": r.text[-2000:]}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def esphome_validate_config(device_name: str) -> dict:
            """
            Validate the ESPHome config for a device.

            Args:
                device_name: Device name.
            """
            try:
                r = httpx.post(f"{url}/{device_name}/validate", timeout=30)
                return r.json()
            except Exception as e:
                return {"error": str(e)}
