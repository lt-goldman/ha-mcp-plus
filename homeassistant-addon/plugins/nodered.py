"""
Node-RED plugin — auto-activated when a0d7b954_nodered is running.

Assumes Node-RED admin auth is disabled (front door open) so the admin API
is accessible without credentials from within the HA Docker network.
"""

import httpx
import json
import logging
import uuid
from typing import Optional, Dict, Any
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.nodered")


class NodeRedPlugin(BasePlugin):
    NAME          = "Node-RED"
    DESCRIPTION   = "Read, create and deploy Node-RED flows via the Admin API"
    ADDON_SLUG    = "nodered"
    INTERNAL_PORT = 1880
    CONFIG_KEY    = "nodered_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url   = cfg.url
        token = cfg.token

        def _headers():
            h = {"Content-Type": "application/json", "Node-RED-API-Version": "v2"}
            if token:
                h["Authorization"] = f"Bearer {token}"
            return h

        @mcp.tool()
        def nodered_health() -> dict:
            """Check Node-RED connectivity and version."""
            try:
                r = httpx.get(f"{url}/settings", headers=_headers(), timeout=5)
                if not r.is_success:
                    log.error(f"[Node-RED] Health check failed: HTTP {r.status_code}")
                    return {"connected": False, "error": f"HTTP {r.status_code}"}
                log.debug(f"[Node-RED] Health check OK at {url}")
                d = r.json()
                return {"connected": True, "version": d.get("version")}
            except httpx.ConnectError:
                log.error(f"[Node-RED] Connection refused at {url} — is Node-RED running?")
                return {"connected": False, "error": f"Cannot connect to Node-RED at {url}"}
            except httpx.TimeoutException:
                log.error(f"[Node-RED] Health check timeout at {url}")
                return {"connected": False, "error": f"Timeout at {url}"}
            except Exception as e:
                log.error(f"[Node-RED] Health check error: {e}")
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def nodered_list_flows() -> dict:
            """List all Node-RED flows with their node counts."""
            try:
                r = httpx.get(f"{url}/flows", headers=_headers(), timeout=10)
                if not r.is_success:
                    log.error(f"[Node-RED] List flows failed: HTTP {r.status_code}")
                    return {"error": f"HTTP {r.status_code}"}
                flows = r.json()
                if not isinstance(flows, list):
                    return {"error": f"Unexpected response: {type(flows).__name__}"}
                nodes = [n for n in flows if isinstance(n, dict)]
                tabs = [n for n in nodes if n.get("type") == "tab"]
                nodes_by_tab = {}
                for n in nodes:
                    tid = n.get("z")
                    if tid:
                        nodes_by_tab.setdefault(tid, []).append(n.get("type"))
                return {
                    "total_nodes": len(nodes),
                    "flows": [
                        {
                            "id": t["id"],
                            "label": t.get("label", "(unlabelled)"),
                            "disabled": t.get("disabled", False),
                            "node_count": len(nodes_by_tab.get(t["id"], [])),
                        }
                        for t in tabs
                    ],
                }
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def nodered_get_flow(flow_id: str) -> dict:
            """Get all nodes for a specific flow tab."""
            try:
                r = httpx.get(f"{url}/flow/{flow_id}", headers=_headers(), timeout=10)
                if not r.is_success:
                    log.error(f"[Node-RED] Get flow {flow_id} failed: HTTP {r.status_code}")
                    return {"error": f"HTTP {r.status_code}"}
                return r.json()
            except httpx.ConnectError:
                log.error(f"[Node-RED] Connection refused at {url}")
                return {"error": f"Cannot connect to Node-RED at {url}"}
            except Exception as e:
                log.error(f"[Node-RED] Get flow {flow_id} error: {e}")
                return {"error": str(e)}

        @mcp.tool()
        def nodered_deploy_flow(flow_json: Dict[str, Any]) -> dict:
            """
            Deploy a new flow to Node-RED.

            Args:
                flow_json: Flow definition dict with 'id', 'label', and 'nodes' array.
            """
            label = flow_json.get("label", flow_json.get("id", "unknown"))
            try:
                r = httpx.post(f"{url}/flow", headers=_headers(), json=flow_json, timeout=15)
                if r.status_code in (200, 204):
                    log.info(f"[Node-RED] Flow '{label}' deployed successfully")
                else:
                    log.error(f"[Node-RED] Deploy flow '{label}' failed: HTTP {r.status_code} — {r.text[:200]}")
                return {"success": r.status_code in (200, 204), "status": r.status_code, "flow_id": flow_json.get("id")}
            except httpx.ConnectError:
                log.error(f"[Node-RED] Connection refused at {url}")
                return {"error": f"Cannot connect to Node-RED at {url}"}
            except Exception as e:
                log.error(f"[Node-RED] Deploy flow '{label}' error: {e}")
                return {"error": str(e)}

        @mcp.tool()
        def nodered_delete_flow(flow_id: str) -> dict:
            """Delete a flow tab from Node-RED."""
            try:
                r = httpx.delete(f"{url}/flow/{flow_id}", headers=_headers(), timeout=10)
                if r.status_code == 204:
                    log.info(f"[Node-RED] Flow {flow_id} deleted")
                else:
                    log.error(f"[Node-RED] Delete flow {flow_id} failed: HTTP {r.status_code}")
                return {"success": r.status_code == 204, "status": r.status_code}
            except httpx.ConnectError:
                log.error(f"[Node-RED] Connection refused at {url}")
                return {"error": f"Cannot connect to Node-RED at {url}"}
            except Exception as e:
                log.error(f"[Node-RED] Delete flow {flow_id} error: {e}")
                return {"error": str(e)}

        @mcp.tool()
        def nodered_build_ha_trigger_flow(
            flow_label: str,
            trigger_entity_id: str,
            trigger_state: str,
            action_service: str,
            action_entity_id: str,
            action_data: Optional[Dict[str, Any]] = None,
        ) -> dict:
            """
            Generate a ready-to-deploy Node-RED flow: triggers on HA entity state change → calls HA service.
            Returns flow JSON to pass to nodered_deploy_flow().

            Args:
                flow_label: Name for the flow tab.
                trigger_entity_id: HA entity to watch (e.g. 'binary_sensor.motion_woonkamer').
                trigger_state: State to trigger on (e.g. 'on').
                action_service: HA service to call (e.g. 'light.turn_on').
                action_entity_id: Target entity for the service.
                action_data: Optional extra service data.
            """
            tab_id = str(uuid.uuid4())[:8]
            n1, n2, n3 = [str(uuid.uuid4())[:8] for _ in range(3)]
            domain, service = (action_service.split(".", 1) + [""])[:2]

            flow = {
                "id": tab_id, "label": flow_label,
                "nodes": [
                    {"id": n1, "type": "trigger-state", "z": tab_id, "name": f"Watch {trigger_entity_id}",
                     "server": "", "version": 6, "entities": {"entity_id": [trigger_entity_id]},
                     "constraints": [{"propertyType": "current_state", "propertyValue": "state",
                                      "comparatorType": "is", "comparatorValue": trigger_state}],
                     "outputs": 1, "wires": [[n2]], "x": 100, "y": 100},
                    {"id": n2, "type": "api-call-service", "z": tab_id, "name": f"Call {action_service}",
                     "server": "", "version": 5, "domain": domain, "service": service,
                     "entityId": [action_entity_id], "data": json.dumps(action_data or {}),
                     "wires": [[n3]], "x": 350, "y": 100},
                    {"id": n3, "type": "debug", "z": tab_id, "name": "Debug",
                     "active": True, "tosidebar": True, "wires": [], "x": 580, "y": 100},
                ]
            }
            return {"flow_json": flow, "hint": "Call nodered_deploy_flow(flow_json=...) to activate."}


# Monkey-patch nodered_deploy_flow with safety guard
# (appended to existing plugin to avoid rewrite)
def _patch_nodered_safety(mcp, url, token):
    from core.safety import plan_nodered_deploy_flow
    import httpx, json, uuid
    from typing import Dict, Any, Optional

    def _headers():
        h = {"Content-Type": "application/json", "Node-RED-API-Version": "v2"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    @mcp.tool()
    def nodered_deploy_flow_safe(
        flow_json: Dict[str, Any],
        execute: bool = False,
    ) -> dict:
        """
        Deploy a new or updated Node-RED flow — with full safety analysis.

        HIGH RISK — shows plan before doing anything.
        Set execute=True only after reviewing and agreeing.

        Args:
            flow_json: Flow definition dict with 'id', 'label', 'nodes'.
            execute: False (default) = show plan only. True = deploy.
        """
        label = flow_json.get("label", flow_json.get("id", "onbekend"))
        nodes = flow_json.get("nodes", [])
        node_types = list(set(n.get("type", "?") for n in nodes))
        summary = f"{len(nodes)} nodes: {', '.join(node_types[:8])}"

        # Check if flow already exists
        is_new = True
        try:
            r = httpx.get(f"{url}/flow/{flow_json.get('id', '')}", headers=_headers(), timeout=5)
            is_new = r.status_code == 404
        except:
            pass

        plan = plan_nodered_deploy_flow(label, summary, is_new)

        if not execute:
            return {
                "status": "PLAN_READY",
                "message": "Nog niets gedeployed. Bekijk het plan.",
                "plan": plan.render(),
                "flow_preview": json.dumps(flow_json, indent=2)[:1000] + ("..." if len(json.dumps(flow_json)) > 1000 else ""),
                "next_step": "Roep deze tool opnieuw aan met execute=True als je akkoord gaat, of bespreek aanpassingen.",
            }

        try:
            r = httpx.post(f"{url}/flow", headers=_headers(), json=flow_json, timeout=15)
            return {
                "success": r.status_code in (200, 204),
                "status": r.status_code,
                "flow_id": flow_json.get("id"),
                "rollback": "Gebruik nodered_delete_flow() om deze flow te verwijderen.",
            }
        except Exception as e:
            return {"error": str(e)}
