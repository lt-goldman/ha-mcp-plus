"""
Zigbee2MQTT plugin — pairing, renaming, network diagnostics, OTA, bindings.

Z2M has no REST API. All operations use:
- MQTT (via HA mqtt.publish service) for commands
- HA entity states for reading bridge/device status

Network map and most bridge requests are fire-and-forget via MQTT;
results appear in the Z2M frontend or in retained MQTT topics.
LQI entities are created per device but disabled by default in HA —
enable them in Settings → Entities if you want z2m_lqi_overview to work.
"""

import httpx
import json
import logging
import os
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.zigbee2mqtt")


class Zigbee2MQTTPlugin(BasePlugin):
    NAME          = "Zigbee2MQTT"
    DESCRIPTION   = "Zigbee pairing, rename, network diagnostics, OTA and bindings via MQTT"
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

        # ── BRIDGE STATUS ───────────────────────────────────────────────────────

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
            """Get Z2M bridge info: version, connection state, permit_join, log level."""
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

        # ── PAIRING ─────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_permit_join(permit: bool = True, device: str = "", duration: int = 254) -> dict:
            """
            Enable or disable Zigbee pairing mode.

            Args:
                permit:   True = allow new devices to join, False = stop pairing.
                device:   Optional: only allow joining via a specific router device.
                duration: Seconds to allow joining (default 254). Only used when device is set.
            """
            if not device:
                # Use HA switch — simpler and gives confirmation
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
            # Via specific router: use MQTT
            result = _bridge_request("permit_join", {"value": permit, "device": device, "time": duration})
            if result.get("ok"):
                status = "ingeschakeld" if permit else "uitgeschakeld"
                return {"ok": True, "message": f"Pairing {status} via router '{device}' voor {duration} seconden."}
            return result

        # ── DEVICE MANAGEMENT ───────────────────────────────────────────────────

        @mcp.tool()
        def z2m_rename_device(friendly_name: str, new_name: str) -> dict:
            """
            Rename a Zigbee device in Z2M.
            The new name also updates the corresponding HA entities.

            Args:
                friendly_name: Current device name as shown in Z2M.
                new_name:      New device name.
            """
            return _bridge_request("device/rename", {"from": friendly_name, "to": new_name})

        @mcp.tool()
        def z2m_interview_device(friendly_name: str) -> dict:
            """
            Re-interview a Zigbee device — forces Z2M to re-discover all capabilities.
            Useful when a device is not fully recognized or missing features.

            Args:
                friendly_name: Device name as shown in Z2M.
            """
            return _bridge_request("device/interview", {"id": friendly_name})

        # ── NETWORK DIAGNOSTICS ─────────────────────────────────────────────────

        @mcp.tool()
        def z2m_health_check() -> dict:
            """
            Request a Z2M bridge health check via MQTT.
            Response appears in the Z2M frontend (bridge/response/health_check).
            """
            return _bridge_request("health_check")

        @mcp.tool()
        def z2m_coordinator_check() -> dict:
            """
            Check if any routers are missing from the coordinator routing table.
            Only works on Texas Instruments adapters (Sonoff dongle, etc.).
            Response contains missingRouters — devices that may cause connectivity issues.
            """
            return _bridge_request("coordinator_check")

        @mcp.tool()
        def z2m_network_map(routes: bool = False) -> dict:
            """
            Request a Zigbee network topology map.
            The result is published to zigbee2mqtt/bridge/response/networkmap and
            visible in the Z2M frontend under Network Map.

            Note: scan takes 10 seconds to 2 minutes depending on network size.
            The network is less responsive during the scan.

            Args:
                routes: Include routing table per link (default False).
            """
            result = _bridge_request("networkmap", {"type": "raw", "routes": routes})
            if result.get("ok"):
                return {
                    "ok": True,
                    "message": "Netwerk scan gestart. Resultaat verschijnt in de Z2M frontend onder 'Network Map'.",
                    "note": "Scan duurt 10 sec tot 2 minuten afhankelijk van netwerk grootte.",
                }
            return result

        @mcp.tool()
        def z2m_lqi_overview() -> dict:
            """
            Get signal quality (LQI) for all Zigbee devices from HA entities.

            Note: LQI sensors are disabled by default in HA.
            Enable them via Settings → Entities → search 'linkquality' → enable.
            LQI range: 0 (bad) to 255 (excellent). Below 50 = poor connection.
            """
            try:
                r = httpx.get(f"{ha_api}/states", headers=_ha_headers(), timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}"}
                states = r.json()
                lqi_entities = [
                    s for s in states
                    if s.get("entity_id", "").endswith("_linkquality")
                    and s.get("entity_id", "").startswith("sensor.")
                ]
                if not lqi_entities:
                    return {
                        "count": 0,
                        "devices": [],
                        "note": "Geen LQI sensors gevonden. Activeer ze via HA Instellingen → Entiteiten → zoek 'linkquality'.",
                    }
                devices = sorted(
                    [
                        {
                            "device": s["entity_id"].replace("sensor.", "").replace("_linkquality", ""),
                            "lqi": s.get("state"),
                            "quality": (
                                "excellent" if s.get("state", "0").isdigit() and int(s["state"]) >= 150
                                else "good" if s.get("state", "0").isdigit() and int(s["state"]) >= 80
                                else "fair" if s.get("state", "0").isdigit() and int(s["state"]) >= 50
                                else "poor"
                            ),
                        }
                        for s in lqi_entities
                    ],
                    key=lambda x: int(x["lqi"]) if str(x["lqi"]).isdigit() else 0,
                )
                return {"count": len(devices), "devices": devices}
            except Exception as e:
                return {"error": str(e)}

        # ── OTA UPDATES ─────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_ota_check(friendly_name: str) -> dict:
            """
            Check if a firmware update is available for a Zigbee device.

            Args:
                friendly_name: Device name as shown in Z2M.
            """
            return _bridge_request("ota_update/check", {"id": friendly_name})

        @mcp.tool()
        def z2m_ota_update(friendly_name: str) -> dict:
            """
            Start a firmware update for a Zigbee device via OTA.
            The device must support OTA updates.
            The update runs in the background — monitor progress in Z2M frontend.

            Args:
                friendly_name: Device name as shown in Z2M.
            """
            return _bridge_request("ota_update/update", {"id": friendly_name})

        # ── BINDINGS ────────────────────────────────────────────────────────────

        @mcp.tool()
        def z2m_bind(source: str, target: str, clusters: list = None) -> dict:
            """
            Bind two Zigbee devices together (direct device-to-device control without coordinator).
            Useful for switches that control lights directly, improving reliability.

            Args:
                source:   Source device name (e.g. the switch).
                target:   Target device name or group name (e.g. the lamp).
                clusters: Optional list of Zigbee clusters to bind, e.g. ['genOnOff', 'genLevelCtrl'].
                          Leave empty to bind default clusters.
            """
            payload: dict = {"from": source, "to": target}
            if clusters:
                payload["clusters"] = clusters
            return _bridge_request("device/bind", payload)

        @mcp.tool()
        def z2m_unbind(source: str, target: str, clusters: list = None) -> dict:
            """
            Remove a binding between two Zigbee devices.

            Args:
                source:   Source device name.
                target:   Target device name or group name.
                clusters: Optional list of clusters to unbind. Leave empty to unbind all.
            """
            payload: dict = {"from": source, "to": target}
            if clusters:
                payload["clusters"] = clusters
            return _bridge_request("device/unbind", payload)

        log.info("[Zigbee2MQTT] Tools registered (pairing, diagnostics, OTA, bindings)")
