"""
Home Assistant core tools — entity states, service calls, history, automations, scripts.

Always active. Connects to HA REST API at http://homeassistant:8123 using the
Supervisor token (injected via homeassistant_api: true in config.yaml).
"""

import os
import httpx
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.homeassistant")

HA_URL = "http://homeassistant:8123"


def _ha_token() -> str:
    """Read HA token from options, then env fallbacks."""
    for key in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN", "HA_TOKEN", "HOMEASSISTANT_TOKEN"):
        t = os.environ.get(key, "")
        if t:
            return t
    # s6 container env files
    for path in [
        "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
        "/run/s6/container_environment/SUPERVISOR_TOKEN",
        "/var/run/s6/container_environment/HASSIO_TOKEN",
        "/run/s6/container_environment/HASSIO_TOKEN",
    ]:
        try:
            with open(path) as f:
                t = f.read().strip()
            if t:
                return t
        except FileNotFoundError:
            pass
    return ""


class HomeAssistantPlugin(BasePlugin):
    NAME          = "HomeAssistant"
    DESCRIPTION   = "Core HA tools: entity states, service calls, history, automations, scripts"
    ADDON_SLUG    = ""   # Always active — loaded explicitly in server.py
    INTERNAL_PORT = 0
    CONFIG_KEY    = ""

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        # Token: prefer explicitly configured ha_token, fall back to Supervisor env
        token = cfg.extra.get("ha_token", "") or _ha_token()
        url   = cfg.extra.get("ha_url", HA_URL).rstrip("/")

        def _headers() -> dict:
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

        def _get(path: str, params: dict = None) -> dict | list:
            try:
                r = httpx.get(f"{url}/api{path}", headers=_headers(), params=params, timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return r.json()
            except httpx.ConnectError:
                return {"error": f"Cannot connect to HA at {url}"}
            except Exception as e:
                return {"error": str(e)}

        def _post(path: str, data: dict = None) -> dict | list:
            try:
                r = httpx.post(f"{url}/api{path}", headers=_headers(), json=data or {}, timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return r.json() if r.text else {"ok": True}
            except Exception as e:
                return {"error": str(e)}

        def _delete(path: str) -> dict:
            try:
                r = httpx.delete(f"{url}/api{path}", headers=_headers(), timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return {"ok": True}
            except Exception as e:
                return {"error": str(e)}

        # ── ENTITY STATES ─────────────────────────────────────────────────────

        @mcp.tool()
        def ha_get_state(entity_id: str) -> dict:
            """Get the current state and attributes of a single entity."""
            return _get(f"/states/{entity_id}")

        @mcp.tool()
        def ha_get_states(domain: str = "") -> dict:
            """
            Get all entity states, optionally filtered by domain.

            Args:
                domain: Optional domain filter (e.g. 'light', 'switch', 'sensor').
                        Leave empty to get all entities.
            """
            states = _get("/states")
            if isinstance(states, dict):  # error
                return states
            if domain:
                states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
            return {
                "count": len(states),
                "states": [
                    {
                        "entity_id": s.get("entity_id"),
                        "state": s.get("state"),
                        "friendly_name": s.get("attributes", {}).get("friendly_name"),
                        "last_changed": s.get("last_changed"),
                    }
                    for s in states
                ],
            }

        @mcp.tool()
        def ha_search_entities(query: str, limit: int = 20) -> dict:
            """
            Search entities by entity_id or friendly name (case-insensitive substring match).

            Args:
                query: Search term (e.g. 'woonkamer', 'sensor.temp', 'light').
                limit: Max results to return (default 20).
            """
            states = _get("/states")
            if isinstance(states, dict):
                return states
            q = query.lower()
            matches = [
                s for s in states
                if q in s.get("entity_id", "").lower()
                or q in s.get("attributes", {}).get("friendly_name", "").lower()
            ]
            return {
                "query": query,
                "count": len(matches),
                "results": [
                    {
                        "entity_id": s.get("entity_id"),
                        "state": s.get("state"),
                        "friendly_name": s.get("attributes", {}).get("friendly_name"),
                        "domain": s.get("entity_id", "").split(".")[0],
                    }
                    for s in matches[:limit]
                ],
            }

        # ── SERVICE CALLS ─────────────────────────────────────────────────────

        @mcp.tool()
        def ha_call_service(
            domain: str,
            service: str,
            entity_id: str = "",
            service_data: dict = None,
        ) -> dict:
            """
            Call a Home Assistant service.

            Args:
                domain:       Service domain, e.g. 'light', 'switch', 'automation'.
                service:      Service name, e.g. 'turn_on', 'turn_off', 'toggle'.
                entity_id:    Target entity (e.g. 'light.woonkamer'). Optional.
                service_data: Extra service data as a dict. Optional.
            """
            body = dict(service_data or {})
            if entity_id:
                body.setdefault("entity_id", entity_id)
            result = _post(f"/services/{domain}/{service}", body)
            if isinstance(result, list):
                return {"ok": True, "changed_states": len(result)}
            return result

        @mcp.tool()
        def ha_list_services(domain: str = "") -> dict:
            """
            List available HA services.

            Args:
                domain: Filter by domain (e.g. 'light'). Leave empty for all.
            """
            services = _get("/services")
            if isinstance(services, dict):
                return services
            if domain:
                services = [s for s in services if s.get("domain") == domain]
            return {
                "count": len(services),
                "services": [
                    {
                        "domain": s.get("domain"),
                        "services": list(s.get("services", {}).keys()),
                    }
                    for s in services
                ],
            }

        @mcp.tool()
        def ha_fire_event(event_type: str, event_data: dict = None) -> dict:
            """
            Fire a Home Assistant event.

            Args:
                event_type: Event type (e.g. 'MY_CUSTOM_EVENT').
                event_data: Optional data dict.
            """
            return _post(f"/events/{event_type}", event_data or {})

        # ── HISTORY & LOGBOOK ────────────────────────────────────────────────

        @mcp.tool()
        def ha_get_history(entity_id: str, hours: int = 24) -> dict:
            """
            Get state history for an entity over the last N hours.

            Args:
                entity_id: Entity to query (e.g. 'sensor.temperatuur').
                hours:     How many hours back to look (default 24).
            """
            start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            result = _get(
                f"/history/period/{start}",
                params={"filter_entity_id": entity_id, "minimal_response": "true"},
            )
            if isinstance(result, dict):
                return result
            # result is [[state, state, ...]] — one list per entity
            history = result[0] if result else []
            return {
                "entity_id": entity_id,
                "hours": hours,
                "count": len(history),
                "history": [
                    {
                        "state": h.get("state"),
                        "last_changed": h.get("last_changed"),
                    }
                    for h in history
                ],
            }

        @mcp.tool()
        def ha_get_logbook(hours: int = 24, entity_id: str = "") -> dict:
            """
            Get logbook entries (events, state changes) for the last N hours.

            Args:
                hours:     How many hours back to look (default 24).
                entity_id: Filter by entity. Leave empty for all.
            """
            start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            params = {}
            if entity_id:
                params["entity"] = entity_id
            result = _get(f"/logbook/{start}", params=params)
            if isinstance(result, dict):
                return result
            return {
                "hours": hours,
                "count": len(result),
                "entries": result[:200],  # cap to avoid huge responses
            }

        # ── UTILITY ───────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_render_template(template: str) -> dict:
            """
            Evaluate a Jinja2 template and return the result.

            Args:
                template: Jinja2 template string, e.g. '{{ states("sensor.temp") }}'.
            """
            result = _post("/template", {"template": template})
            if isinstance(result, dict):
                return result
            return {"result": result}

        @mcp.tool()
        def ha_get_config() -> dict:
            """Get Home Assistant configuration info (version, location, components)."""
            return _get("/config")

        # ── AUTOMATIONS ───────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_automations() -> dict:
            """List all automations with their state (on/off) and friendly name."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            automations = [s for s in states if s.get("entity_id", "").startswith("automation.")]
            return {
                "count": len(automations),
                "automations": [
                    {
                        "entity_id": s.get("entity_id"),
                        "friendly_name": s.get("attributes", {}).get("friendly_name"),
                        "state": s.get("state"),
                        "last_triggered": s.get("attributes", {}).get("last_triggered"),
                    }
                    for s in automations
                ],
            }

        @mcp.tool()
        def ha_get_automation(automation_id: str) -> dict:
            """
            Get the full config of an automation.

            Args:
                automation_id: The automation ID (e.g. 'my_automation' or full entity_id
                               'automation.my_automation' — prefix is stripped automatically).
            """
            aid = automation_id.removeprefix("automation.")
            return _get(f"/config/automation/config/{aid}")

        @mcp.tool()
        def ha_set_automation(automation_id: str, config: dict) -> dict:
            """
            Create or update an automation.

            Args:
                automation_id: Automation ID (without 'automation.' prefix).
                config:        Full automation config as a dict (same structure as YAML).
            """
            aid = automation_id.removeprefix("automation.")
            r = httpx.post(
                f"{url}/api/config/automation/config/{aid}",
                headers=_headers(),
                json=config,
                timeout=15,
            )
            if not r.is_success:
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
            return r.json() if r.text else {"ok": True}

        @mcp.tool()
        def ha_delete_automation(automation_id: str) -> dict:
            """
            Delete an automation.

            Args:
                automation_id: Automation ID (without 'automation.' prefix).
            """
            aid = automation_id.removeprefix("automation.")
            return _delete(f"/config/automation/config/{aid}")

        # ── SCRIPTS ───────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_scripts() -> dict:
            """List all scripts with their state and friendly name."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            scripts = [s for s in states if s.get("entity_id", "").startswith("script.")]
            return {
                "count": len(scripts),
                "scripts": [
                    {
                        "entity_id": s.get("entity_id"),
                        "friendly_name": s.get("attributes", {}).get("friendly_name"),
                        "state": s.get("state"),
                    }
                    for s in scripts
                ],
            }

        @mcp.tool()
        def ha_get_script(script_id: str) -> dict:
            """
            Get the full config of a script.

            Args:
                script_id: Script ID (e.g. 'my_script' or 'script.my_script').
            """
            sid = script_id.removeprefix("script.")
            return _get(f"/config/script/config/{sid}")

        @mcp.tool()
        def ha_set_script(script_id: str, config: dict) -> dict:
            """
            Create or update a script.

            Args:
                script_id: Script ID (without 'script.' prefix).
                config:    Full script config as a dict.
            """
            sid = script_id.removeprefix("script.")
            r = httpx.post(
                f"{url}/api/config/script/config/{sid}",
                headers=_headers(),
                json=config,
                timeout=15,
            )
            if not r.is_success:
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
            return r.json() if r.text else {"ok": True}

        @mcp.tool()
        def ha_delete_script(script_id: str) -> dict:
            """
            Delete a script.

            Args:
                script_id: Script ID (without 'script.' prefix).
            """
            sid = script_id.removeprefix("script.")
            return _delete(f"/config/script/config/{sid}")

        # ── HELPERS ───────────────────────────────────────────────────────────

        _HELPER_DOMAINS = {
            "input_boolean", "input_number", "input_text",
            "input_select", "input_datetime", "input_button",
            "counter", "timer", "schedule",
        }

        @mcp.tool()
        def ha_list_helpers() -> dict:
            """List all helper entities (input_boolean, input_number, counter, timer, etc.)."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            helpers = [
                s for s in states
                if s.get("entity_id", "").split(".")[0] in _HELPER_DOMAINS
            ]
            return {
                "count": len(helpers),
                "helpers": [
                    {
                        "entity_id": s.get("entity_id"),
                        "domain": s.get("entity_id", "").split(".")[0],
                        "friendly_name": s.get("attributes", {}).get("friendly_name"),
                        "state": s.get("state"),
                    }
                    for s in helpers
                ],
            }

        log.info("[HomeAssistant] Core HA tools registered")
