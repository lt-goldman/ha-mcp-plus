"""
ESPHome plugin — auto-activated when 5c53de3b_esphome is running.

This is a good example of how simple it is to add a new plugin:
1. Subclass BasePlugin
2. Set ADDON_SLUG, INTERNAL_PORT, NAME
3. Implement register_tools()
That's it — discovery and loading is automatic!
"""

import httpx
import logging
from typing import Optional
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.esphome")


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
                if r.status_code != 200:
                    log.error(f"[ESPHome] Health check failed: HTTP {r.status_code}")
                    return {"connected": False, "error": f"HTTP {r.status_code}"}
                log.debug(f"[ESPHome] Health check OK at {url}")
                return {"connected": True}
            except httpx.ConnectError:
                log.error(f"[ESPHome] Connection refused at {url} — is ESPHome running?")
                return {"connected": False, "error": f"Cannot connect to ESPHome at {url}"}
            except httpx.TimeoutException:
                log.error(f"[ESPHome] Health check timeout at {url}")
                return {"connected": False, "error": f"Timeout at {url}"}
            except Exception as e:
                log.error(f"[ESPHome] Health check error: {e}")
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def esphome_list_devices() -> dict:
            """
            List all ESPHome devices with their online/offline status.
            """
            try:
                r = httpx.get(f"{url}/devices.json", timeout=10)
                if not r.is_success:
                    log.error(f"[ESPHome] List devices failed: HTTP {r.status_code}")
                    return {"error": f"HTTP {r.status_code}"}
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
            except httpx.ConnectError:
                log.error(f"[ESPHome] Connection refused at {url}")
                return {"error": f"Cannot connect to ESPHome at {url}"}
            except Exception as e:
                log.error(f"[ESPHome] List devices error: {e}")
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
                if not r.is_success:
                    log.error(f"[ESPHome] Get logs for '{device_name}' failed: HTTP {r.status_code}")
                    return {"error": f"HTTP {r.status_code}"}
                return {"device": device_name, "logs": r.text[-2000:]}
            except httpx.ConnectError:
                log.error(f"[ESPHome] Connection refused at {url}")
                return {"error": f"Cannot connect to ESPHome at {url}"}
            except Exception as e:
                log.error(f"[ESPHome] Get logs for '{device_name}' error: {e}")
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
                if not r.is_success:
                    log.error(f"[ESPHome] Validate '{device_name}' failed: HTTP {r.status_code}")
                    return {"error": f"HTTP {r.status_code}"}
                return r.json()
            except httpx.ConnectError:
                log.error(f"[ESPHome] Connection refused at {url}")
                return {"error": f"Cannot connect to ESPHome at {url}"}
            except Exception as e:
                log.error(f"[ESPHome] Validate '{device_name}' error: {e}")
                return {"error": str(e)}
