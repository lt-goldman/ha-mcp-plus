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
        ha_api     = "http://homeassistant:8123/api"
        base_topic = "zigbee2mqtt"

        def _ha_token() -> str:
            for key in ("HA_REST_TOKEN", "SUPERVISOR_TOKEN", "HASSIO_TOKEN", "HA_TOKEN"):
                t = os.environ.get(key, "")
                if t:
                    return t
            return cfg.extra.get("ha_token", "")

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
            conn = _get_state("binary_sensor.zigbee2mqtt_bridge_connection_state")
            if "error" not in conn:
                return {
                    "connected": conn.get("state") == "on",
                    "state": conn.get("state"),
                    "attributes": conn.get("attributes", {}),
                }
            return conn

        @mcp.tool()
        def z2m_bridge_info() -> dict:
            """
            Get Z2M bridge info (version, connection, permit_join) from HA entities.
            """
            result = {}
            entities = {
                "connection": "binary_sensor.zigbee2mqtt_bridge_connection_state",
                "version": "sensor.zigbee2mqtt_bridge_version",
                "permit_join": "switch.zigbee2mqtt_bridge_permit_join",
                "log_level": "select.zigbee2mqtt_bridge_log_level",
            }
            for key, entity_id in entities.items():
                s = _get_state(entity_id)
                if "error" not in s:
                    result[key] = s.get("state")
            if not result:
                return {"error": "No Z2M bridge entities found in HA."}
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
                device:   Optional: only allow joining via a specific router device (MQTT).
                duration: Seconds to allow joining (default 254, only via MQTT path).
            """
            # If no specific device/duration, use the HA switch (simplest)
            if not device and duration == 254:
                service = "turn_on" if permit else "turn_off"
                try:
                    r = httpx.post(
                        f"{ha_api}/services/switch/{service}",
                        headers=_ha_headers(),
                        json={"entity_id": "switch.zigbee2mqtt_bridge_permit_join"},
                        timeout=10,
                    )
                    if r.is_success:
                        status = "ingeschakeld" if permit else "uitgeschakeld"
                        return {"ok": True, "message": f"Pairing {status}."}
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
                except Exception as e:
                    return {"error": str(e)}
            # Advanced: specific device or duration → MQTT
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
