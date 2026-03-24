"""
Zigbee2MQTT plugin — bridge control and device management.

Z2M has no REST API. All operations use:
- MQTT (via HA mqtt.publish service) for commands/control
- HA entity states for reading bridge/device status
"""

import httpx
import json
import logging
import os
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.zigbee2mqtt")


class Zigbee2MQTTPlugin(BasePlugin):
    NAME          = "Zigbee2MQTT"
    DESCRIPTION   = "Control Zigbee devices and bridge via MQTT (through HA)"
    ADDON_SLUG    = "zigbee2mqtt"
    INTERNAL_PORT = 8099   # used only for addon discovery check, not for HTTP calls
    CONFIG_KEY    = "z2m_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        ha_api    = "http://supervisor/core/api"
        base_topic = "zigbee2mqtt"

        def _ha_token() -> str:
            for t in [os.environ.get("SUPERVISOR_TOKEN"), os.environ.get("HASSIO_TOKEN")]:
                if t:
                    return t
            try:
                with open("/proc/1/environ", "rb") as f:
                    for part in f.read().split(b"\x00"):
                        if part.startswith(b"SUPERVISOR_TOKEN="):
                            t = part.split(b"=", 1)[1].decode().strip()
                            if t:
                                return t
            except Exception:
                pass
            return cfg.extra.get("ha_token", "") or os.environ.get("HA_REST_TOKEN", "")

        def _ha_headers() -> dict:
            return {"Authorization": f"Bearer {_ha_token()}", "Content-Type": "application/json"}

        def _get_state(entity_id: str) -> dict:
            try:
                r = httpx.get(f"{ha_api}/states/{entity_id}", headers=_ha_headers(), timeout=10)
                if r.status_code == 200:
                    return r.json()
                return {"error": f"HTTP {r.status_code}"}
            except Exception as e:
                return {"error": str(e)}

        def _mqtt_publish(topic: str, payload) -> dict:
            try:
                r = httpx.post(
                    f"{ha_api}/services/mqtt/publish",
                    headers=_ha_headers(),
                    json={
                        "topic": topic,
                        "payload": json.dumps(payload) if isinstance(payload, dict) else str(payload),
                    },
                    timeout=10,
                )
                if r.is_success:
                    return {"ok": True, "topic": topic}
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
            except Exception as e:
                return {"error": str(e)}

        def _bridge_request(action: str, payload: dict = None) -> dict:
            return _mqtt_publish(f"{base_topic}/bridge/request/{action}", payload or {})

        # ── BRIDGE ─────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_health() -> dict:
            """Check Zigbee2MQTT bridge status via HA entity state."""
            state = _get_state("sensor.zigbee2mqtt_bridge_state")
            if "error" not in state:
                return {
                    "connected": state.get("state") == "online",
                    "state": state.get("state"),
                    "attributes": state.get("attributes", {}),
                }
            return state

        @mcp.tool()
        def z2m_bridge_info() -> dict:
            """
            Get Z2M bridge info (version, coordinator, channel) from HA entities.
            Device states and info are available via HA entities created by Z2M.
            """
            result = {}
            for entity in ["sensor.zigbee2mqtt_bridge_state", "sensor.zigbee2mqtt_bridge_version"]:
                s = _get_state(entity)
                if "error" not in s:
                    key = entity.split(".")[-1].replace("zigbee2mqtt_bridge_", "")
                    result[key] = {"state": s.get("state"), **s.get("attributes", {})}
            if not result:
                return {
                    "error": "No Z2M bridge entities found in HA.",
                    "hint": "Check entity names in Developer Tools → States (search 'zigbee2mqtt').",
                }
            return result

        @mcp.tool()
        def z2m_bridge_config() -> dict:
            """
            Request Z2M to publish its config to MQTT.
            Bridge configuration attributes are also visible on HA entities.
            """
            return _bridge_request("config/get")

        @mcp.tool()
        def z2m_permit_join(permit: bool = True, device: str = "", duration: int = 254) -> dict:
            """
            Enable or disable Zigbee pairing mode.

            Args:
                permit:   True = allow new devices to join, False = block joining.
                device:   Optional: only allow joining via a specific router device.
                duration: Seconds to allow joining (default 254).
            """
            payload: dict = {"value": permit, "time": duration}
            if device:
                payload["device"] = device
            result = _bridge_request("permit_join", payload)
            if result.get("ok"):
                status = "ingeschakeld" if permit else "uitgeschakeld"
                return {"ok": True, "message": f"Pairing {status} voor {duration} seconden."}
            return result

        @mcp.tool()
        def z2m_rename_device(friendly_name: str, new_name: str) -> dict:
            """
            Rename a Zigbee device in Z2M.

            Args:
                friendly_name: Current device name (as shown in Z2M).
                new_name:      New device name.
            """
            return _bridge_request("device/rename", {"from": friendly_name, "to": new_name})

        # ── DEVICES ────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_device_set(friendly_name: str, payload: dict) -> dict:
            """
            Send a command to a Zigbee device via MQTT.

            Args:
                friendly_name: Device name as configured in Z2M.
                payload:       Command, e.g. {'state': 'ON'} or {'brightness': 128, 'color_temp': 300}.
            """
            return _mqtt_publish(f"{base_topic}/{friendly_name}/set", payload)

        @mcp.tool()
        def z2m_device_get(friendly_name: str) -> dict:
            """
            Request current state from a Zigbee device via MQTT.

            Args:
                friendly_name: Device name as configured in Z2M.
            """
            return _mqtt_publish(f"{base_topic}/{friendly_name}/get", {"state": ""})

        @mcp.tool()
        def z2m_list_devices() -> dict:
            """
            Request Z2M to republish all device info to MQTT.
            Use ha_search_entities or ha_list_devices to see devices as HA knows them.
            """
            result = _bridge_request("devices/get")
            return {
                "ok": result.get("ok", False),
                "hint": "Use ha_search_entities('zigbee2mqtt') or ha_list_devices() to list devices in HA.",
                "mqtt_result": result,
            }

        @mcp.tool()
        def z2m_get_device(friendly_name: str) -> dict:
            """
            Request Z2M to republish state for a specific device.
            Current state is available via HA entities (ha_get_state).

            Args:
                friendly_name: Device name as configured in Z2M.
            """
            result = _mqtt_publish(f"{base_topic}/{friendly_name}/get", {"state": ""})
            return {
                "ok": result.get("ok", False),
                "hint": f"Use ha_get_state to read current state of HA entities for '{friendly_name}'.",
                "mqtt_result": result,
            }

        # ── GROUPS ─────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_group_set(friendly_name: str, payload: dict) -> dict:
            """
            Send a command to a Zigbee group via MQTT.

            Args:
                friendly_name: Group name as configured in Z2M.
                payload:       Command, e.g. {'state': 'OFF'}.
            """
            return _mqtt_publish(f"{base_topic}/{friendly_name}/set", payload)

        @mcp.tool()
        def z2m_list_groups() -> dict:
            """
            Request Z2M to republish group info to MQTT.
            Groups are also visible as HA entities.
            """
            return _bridge_request("groups/get")

        log.info("[Zigbee2MQTT] Tools registered (MQTT-based via HA)")
