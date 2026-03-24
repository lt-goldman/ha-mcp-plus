"""
ESPHome plugin — auto-activated when esphome is running.
"""

import glob
import httpx
import logging
import os
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.esphome")

ESPHOME_CONFIG_DIR = "/config/esphome"


class ESPHomePlugin(BasePlugin):
    NAME          = "ESPHome"
    DESCRIPTION   = "Manage ESPHome devices — read/write configs, compile, OTA updates"
    ADDON_SLUG    = "esphome"
    INTERNAL_PORT = 6052
    CONFIG_KEY    = ""  # ESPHome uses HA auth, no separate token

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url

        def _headers() -> dict:
            # ESPHome bypasses its own auth for ingress requests via X-HA-Ingress header
            return {"X-HA-Ingress": "true"}

        @mcp.tool()
        def esphome_health() -> dict:
            """Check ESPHome connectivity."""
            try:
                r = httpx.get(f"{url}/", timeout=5, follow_redirects=True, headers=_headers())
                if not r.is_success:
                    return {"connected": False, "error": f"HTTP {r.status_code}"}
                return {"connected": True}
            except httpx.ConnectError:
                return {"connected": False, "error": f"Cannot connect to ESPHome at {url}"}
            except httpx.TimeoutException:
                return {"connected": False, "error": f"Timeout at {url}"}
            except Exception as e:
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def esphome_list_devices() -> dict:
            """List all ESPHome devices by reading config files from /config/esphome/."""
            try:
                yaml_files = glob.glob(f"{ESPHOME_CONFIG_DIR}/*.yaml")
                devices = []
                for path in sorted(yaml_files):
                    name = os.path.basename(path).removesuffix(".yaml")
                    # Skip ESPHome's own internal files
                    if name.startswith("."):
                        continue
                    devices.append({"name": name, "config_path": path})
                return {"count": len(devices), "devices": devices}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def esphome_read_config(device_name: str) -> dict:
            """
            Read the ESPHome YAML config for a device.

            Args:
                device_name: Device name (without .yaml extension).
            """
            name = device_name.removesuffix(".yaml")
            path = f"{ESPHOME_CONFIG_DIR}/{name}.yaml"
            try:
                with open(path) as f:
                    content = f.read()
                return {"device": name, "path": path, "content": content}
            except FileNotFoundError:
                return {"error": f"Config not found: {path}"}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def esphome_write_config(device_name: str, yaml_content: str) -> dict:
            """
            Write (create or overwrite) an ESPHome YAML config for a device.
            After writing, call esphome_compile to build the firmware.

            Args:
                device_name:  Device name (without .yaml extension).
                yaml_content: Full ESPHome YAML configuration.
            """
            name = device_name.removesuffix(".yaml")
            path = f"{ESPHOME_CONFIG_DIR}/{name}.yaml"
            try:
                os.makedirs(ESPHOME_CONFIG_DIR, exist_ok=True)
                with open(path, "w") as f:
                    f.write(yaml_content)
                log.info(f"[ESPHome] Config written: {path}")
                return {"written": True, "path": path, "device": name}
            except Exception as e:
                log.error(f"[ESPHome] Write config error: {e}")
                return {"error": str(e)}

        @mcp.tool()
        def esphome_compile(device_name: str) -> dict:
            """
            Compile the ESPHome firmware for a device.
            Streams the build log from the ESPHome API and returns the result.

            Args:
                device_name: Device name (without .yaml extension).
            """
            name = device_name.removesuffix(".yaml")
            config_file = f"{name}.yaml"
            try:
                lines = []
                success = False
                with httpx.stream(
                    "POST",
                    f"{url}/compile",
                    json={"configuration": config_file},
                    headers=_headers(),
                    timeout=300,
                ) as r:
                    if not r.is_success:
                        return {"error": f"HTTP {r.status_code}", "device": name}
                    for line in r.iter_lines():
                        if not line:
                            continue
                        lines.append(line)
                        if "Successfully compiled" in line:
                            success = True
                        if "ERROR" in line or "error" in line.lower():
                            log.warning(f"[ESPHome] Compile: {line}")

                log.info(f"[ESPHome] Compile {'OK' if success else 'FAILED'}: {name}")
                return {
                    "device": name,
                    "success": success,
                    "log": lines,
                }
            except httpx.ConnectError:
                return {"error": f"Cannot connect to ESPHome at {url}", "device": name}
            except Exception as e:
                log.error(f"[ESPHome] Compile error: {e}")
                return {"error": str(e), "device": name}

        @mcp.tool()
        def esphome_upload(device_name: str) -> dict:
            """
            Upload (OTA flash) the compiled firmware to an ESPHome device.
            The device must be online and reachable. Run esphome_compile first.

            Args:
                device_name: Device name (without .yaml extension).
            """
            name = device_name.removesuffix(".yaml")
            config_file = f"{name}.yaml"
            try:
                lines = []
                success = False
                with httpx.stream(
                    "POST",
                    f"{url}/upload",
                    json={"configuration": config_file},
                    headers=_headers(),
                    timeout=300,
                ) as r:
                    if not r.is_success:
                        return {"error": f"HTTP {r.status_code}", "device": name}
                    for line in r.iter_lines():
                        if not line:
                            continue
                        lines.append(line)
                        if "Successfully uploaded" in line or "OTA successful" in line:
                            success = True

                log.info(f"[ESPHome] Upload {'OK' if success else 'FAILED'}: {name}")
                return {
                    "device": name,
                    "success": success,
                    "log": lines,
                }
            except httpx.ConnectError:
                return {"error": f"Cannot connect to ESPHome at {url}", "device": name}
            except Exception as e:
                log.error(f"[ESPHome] Upload error: {e}")
                return {"error": str(e), "device": name}

        @mcp.tool()
        def esphome_get_device_logs(device_name: str) -> dict:
            """
            Get recent logs from an ESPHome device.

            Note: ESPHome log streaming requires a WebSocket connection — not yet supported.
            Use the ESPHome dashboard directly for live logs.

            Args:
                device_name: Device name.
            """
            return {
                "error": "not_supported",
                "message": "ESPHome log streaming requires WebSocket — not yet implemented. Use the ESPHome dashboard for live logs.",
            }
