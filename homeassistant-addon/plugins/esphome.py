"""
ESPHome plugin — auto-activated when esphome is running.
"""

import httpx
import logging
import os
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.esphome")


class ESPHomePlugin(BasePlugin):
    NAME          = "ESPHome"
    DESCRIPTION   = "Manage ESPHome devices, check logs, trigger OTA updates"
    ADDON_SLUG    = "esphome"
    INTERNAL_PORT = 6052
    CONFIG_KEY    = ""  # ESPHome uses HA auth, no separate token

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url

        def _headers() -> dict:
            token = os.environ.get("SUPERVISOR_TOKEN", "")
            return {"Authorization": f"Bearer {token}"} if token else {}

        @mcp.tool()
        def esphome_health() -> dict:
            """Check ESPHome connectivity."""
            try:
                r = httpx.get(f"{url}/", timeout=5, follow_redirects=True, headers=_headers())
                if not r.is_success:
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
                r = httpx.get(f"{url}/devices", timeout=10, follow_redirects=True, headers=_headers())
                if not r.is_success:
                    log.error(f"[ESPHome] List devices failed: HTTP {r.status_code}")
                    return {"error": f"HTTP {r.status_code}"}
                data = r.json()
                # ESPHome /devices returns {"configured": [...], "importable": [...]}
                devices = data.get("configured", data) if isinstance(data, dict) else data
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

            Note: ESPHome log streaming requires a WebSocket connection, which is
            not yet supported. Use the ESPHome dashboard directly for live logs.

            Args:
                device_name: Device name (as shown in ESPHome dashboard).
            """
            return {
                "error": "not_supported",
                "message": "ESPHome log streaming requires WebSocket — not yet implemented. Use the ESPHome dashboard for live logs.",
            }

        @mcp.tool()
        def esphome_validate_config(device_name: str) -> dict:
            """
            Validate the ESPHome config for a device.

            Note: ESPHome config validation requires a WebSocket connection, which is
            not yet supported.

            Args:
                device_name: Device name.
            """
            return {
                "error": "not_supported",
                "message": "ESPHome config validation requires WebSocket — not yet implemented.",
            }
