"""
Home Assistant core tools — complete HA REST API coverage.

Always active. Connects to HA REST API at http://homeassistant:8123 using the
Supervisor token (injected via homeassistant_api: true in config.yaml).

Categories:
  - Entity states & search
  - Service calls & events
  - History & logbook
  - Utility (template, config, system health)
  - Entity registry
  - Device registry
  - Area registry
  - Floor registry
  - Label registry
  - Zones
  - Dashboard (Lovelace)
  - Calendar
  - Todo lists
  - Automations (CRUD)
  - Scripts (CRUD)
  - Helpers
  - Scenes & groups
  - Updates
  - Automation traces
"""

import os
import httpx
import logging
from datetime import datetime, timedelta, timezone

from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.homeassistant")

HA_URL = "http://homeassistant:8123"


def _ha_token() -> str:
    for key in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN", "HA_REST_TOKEN", "HA_TOKEN", "HOMEASSISTANT_TOKEN"):
        t = os.environ.get(key, "")
        if t:
            return t
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
    DESCRIPTION   = "Core HA tools: states, services, history, registry, automations, calendar, todo"
    ADDON_SLUG    = ""   # Always active — loaded explicitly in server.py
    INTERNAL_PORT = 0
    CONFIG_KEY    = ""

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        token = cfg.extra.get("ha_token", "") or _ha_token()
        url   = cfg.extra.get("ha_url", HA_URL).rstrip("/")

        def _headers() -> dict:
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

        def _get(path: str, params: dict = None):
            try:
                r = httpx.get(f"{url}/api{path}", headers=_headers(), params=params, timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return r.json()
            except httpx.ConnectError:
                return {"error": f"Cannot connect to HA at {url}"}
            except Exception as e:
                return {"error": str(e)}

        def _post(path: str, data: dict = None, params: dict = None):
            try:
                r = httpx.post(f"{url}/api{path}", headers=_headers(), json=data or {}, params=params, timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return r.json() if r.text.strip() else {"ok": True}
            except Exception as e:
                return {"error": str(e)}

        def _delete(path: str):
            try:
                r = httpx.delete(f"{url}/api{path}", headers=_headers(), timeout=15)
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                return {"ok": True}
            except Exception as e:
                return {"error": str(e)}

        def _service(domain: str, service: str, data: dict, return_response: bool = False):
            params = {"return_response": "true"} if return_response else None
            result = _post(f"/services/{domain}/{service}", data, params=params)
            if isinstance(result, list):
                return {"ok": True, "changed_states": len(result)}
            return result

        # ── ENTITY STATES & SEARCH ────────────────────────────────────────────

        @mcp.tool()
        def ha_get_state(entity_id: str) -> dict:
            """Get the current state and attributes of a single entity."""
            return _get(f"/states/{entity_id}")

        @mcp.tool()
        def ha_get_states(domain: str = "") -> dict:
            """
            Get all entity states, optionally filtered by domain.

            Args:
                domain: e.g. 'light', 'switch', 'sensor'. Empty = all entities.
            """
            states = _get("/states")
            if isinstance(states, dict):
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
            Search entities by entity_id or friendly name (case-insensitive).

            Args:
                query: Search term, e.g. 'woonkamer', 'light', 'sensor.temp'.
                limit: Max results (default 20).
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

        # ── SERVICE CALLS & EVENTS ────────────────────────────────────────────

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
                domain:       e.g. 'light', 'switch', 'automation', 'climate'.
                service:      e.g. 'turn_on', 'turn_off', 'toggle', 'set_temperature'.
                entity_id:    Target entity. Optional.
                service_data: Extra parameters as dict. Optional.
            """
            body = dict(service_data or {})
            if entity_id:
                body.setdefault("entity_id", entity_id)
            return _service(domain, service, body)

        @mcp.tool()
        def ha_list_services(domain: str = "") -> dict:
            """
            List available HA services, optionally filtered by domain.

            Args:
                domain: e.g. 'light'. Empty = all domains.
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
                event_type: e.g. 'MY_CUSTOM_EVENT'.
                event_data: Optional data dict.
            """
            return _post(f"/events/{event_type}", event_data or {})

        # ── HISTORY & LOGBOOK ────────────────────────────────────────────────

        @mcp.tool()
        def ha_get_history(entity_id: str, hours: int = 24) -> dict:
            """
            Get state history for an entity over the last N hours.

            Args:
                entity_id: e.g. 'sensor.temperatuur'.
                hours:     How many hours back (default 24).
            """
            start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            result = _get(
                f"/history/period/{start}",
                params={"filter_entity_id": entity_id, "minimal_response": "true"},
            )
            if isinstance(result, dict):
                return result
            history = result[0] if result else []
            return {
                "entity_id": entity_id,
                "hours": hours,
                "count": len(history),
                "history": [
                    {"state": h.get("state"), "last_changed": h.get("last_changed")}
                    for h in history
                ],
            }

        @mcp.tool()
        def ha_get_logbook(hours: int = 24, entity_id: str = "") -> dict:
            """
            Get logbook entries for the last N hours.

            Args:
                hours:     How many hours back (default 24).
                entity_id: Filter by entity. Empty = all.
            """
            start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            params = {}
            if entity_id:
                params["entity"] = entity_id
            result = _get(f"/logbook/{start}", params=params)
            if isinstance(result, dict):
                return result
            return {"hours": hours, "count": len(result), "entries": result[:200]}

        # ── UTILITY ───────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_render_template(template: str) -> dict:
            """
            Evaluate a Jinja2 template.

            Args:
                template: e.g. '{{ states("sensor.temp") }}'.
            """
            result = _post("/template", {"template": template})
            if isinstance(result, dict):
                return result
            return {"result": result}

        @mcp.tool()
        def ha_get_config() -> dict:
            """Get HA configuration info (version, location, components)."""
            return _get("/config")

        @mcp.tool()
        def ha_get_system_health() -> dict:
            """Get system health status for HA and all integrations."""
            return _get("/system_health")

        # ── ENTITY REGISTRY ───────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_entity_registry(domain: str = "") -> dict:
            """
            List all entities in the entity registry (includes disabled entities).

            Args:
                domain: Optional filter, e.g. 'light'.
            """
            entries = _get("/config/entity_registry")
            if isinstance(entries, dict):
                return entries
            if domain:
                entries = [e for e in entries if e.get("entity_id", "").startswith(f"{domain}.")]
            return {
                "count": len(entries),
                "entities": [
                    {
                        "entity_id": e.get("entity_id"),
                        "name": e.get("name") or e.get("original_name"),
                        "platform": e.get("platform"),
                        "area_id": e.get("area_id"),
                        "disabled_by": e.get("disabled_by"),
                        "device_id": e.get("device_id"),
                    }
                    for e in entries
                ],
            }

        @mcp.tool()
        def ha_update_entity(
            entity_id: str,
            name: str = "",
            icon: str = "",
            area_id: str = "",
            disabled: bool = None,
        ) -> dict:
            """
            Update entity registry properties.

            Args:
                entity_id: Entity to update.
                name:      Custom name. Empty = keep current.
                icon:      Custom icon (e.g. 'mdi:lightbulb'). Empty = keep current.
                area_id:   Assign to area. Empty = keep current.
                disabled:  True to disable, False to enable, None = keep current.
            """
            body = {}
            if name:
                body["name"] = name
            if icon:
                body["icon"] = icon
            if area_id:
                body["area_id"] = area_id
            if disabled is not None:
                body["disabled_by"] = "user" if disabled else None
            return _post(f"/config/entity_registry/{entity_id}", body)

        @mcp.tool()
        def ha_remove_entity(entity_id: str) -> dict:
            """
            Remove an entity from the entity registry.

            Args:
                entity_id: Entity to remove.
            """
            return _delete(f"/config/entity_registry/{entity_id}")

        # ── DEVICE REGISTRY ───────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_devices(area_id: str = "") -> dict:
            """
            List all devices in the device registry.

            Args:
                area_id: Filter by area ID. Empty = all devices.
            """
            devices = _get("/config/device_registry")
            if isinstance(devices, dict):
                return devices
            if area_id:
                devices = [d for d in devices if d.get("area_id") == area_id]
            return {
                "count": len(devices),
                "devices": [
                    {
                        "id": d.get("id"),
                        "name": d.get("name_by_user") or d.get("name"),
                        "manufacturer": d.get("manufacturer"),
                        "model": d.get("model"),
                        "area_id": d.get("area_id"),
                        "disabled_by": d.get("disabled_by"),
                    }
                    for d in devices
                ],
            }

        @mcp.tool()
        def ha_update_device(
            device_id: str,
            name: str = "",
            area_id: str = "",
            disabled: bool = None,
        ) -> dict:
            """
            Update device registry properties.

            Args:
                device_id: Device ID (from ha_list_devices).
                name:      Custom name. Empty = keep current.
                area_id:   Assign to area. Empty = keep current.
                disabled:  True to disable, False to enable, None = keep current.
            """
            body = {}
            if name:
                body["name_by_user"] = name
            if area_id:
                body["area_id"] = area_id
            if disabled is not None:
                body["disabled_by"] = "user" if disabled else None
            return _post(f"/config/device_registry/{device_id}", body)

        # ── AREA REGISTRY ─────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_areas() -> dict:
            """List all areas in the area registry."""
            areas = _get("/config/area_registry")
            if isinstance(areas, dict):
                return areas
            return {
                "count": len(areas),
                "areas": [
                    {
                        "area_id": a.get("area_id"),
                        "name": a.get("name"),
                        "floor_id": a.get("floor_id"),
                        "aliases": a.get("aliases", []),
                    }
                    for a in areas
                ],
            }

        @mcp.tool()
        def ha_create_area(name: str, floor_id: str = "", aliases: list = None) -> dict:
            """
            Create a new area.

            Args:
                name:     Area name.
                floor_id: Assign to floor. Optional.
                aliases:  Alternative names. Optional.
            """
            body = {"name": name}
            if floor_id:
                body["floor_id"] = floor_id
            if aliases:
                body["aliases"] = aliases
            return _post("/config/area_registry", body)

        @mcp.tool()
        def ha_update_area(area_id: str, name: str = "", floor_id: str = "", aliases: list = None) -> dict:
            """
            Update an existing area.

            Args:
                area_id:  Area ID (from ha_list_areas).
                name:     New name. Empty = keep current.
                floor_id: New floor. Empty = keep current.
                aliases:  New aliases. None = keep current.
            """
            body = {}
            if name:
                body["name"] = name
            if floor_id:
                body["floor_id"] = floor_id
            if aliases is not None:
                body["aliases"] = aliases
            return _post(f"/config/area_registry/{area_id}", body)

        @mcp.tool()
        def ha_delete_area(area_id: str) -> dict:
            """
            Delete an area.

            Args:
                area_id: Area ID (from ha_list_areas).
            """
            return _delete(f"/config/area_registry/{area_id}")

        # ── FLOOR REGISTRY ────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_floors() -> dict:
            """List all floors in the floor registry."""
            floors = _get("/config/floor_registry")
            if isinstance(floors, dict):
                return floors
            return {
                "count": len(floors),
                "floors": [
                    {
                        "floor_id": f.get("floor_id"),
                        "name": f.get("name"),
                        "level": f.get("level"),
                        "aliases": f.get("aliases", []),
                    }
                    for f in floors
                ],
            }

        @mcp.tool()
        def ha_create_floor(name: str, level: int = None, aliases: list = None) -> dict:
            """
            Create a new floor.

            Args:
                name:    Floor name (e.g. 'Begane grond').
                level:   Floor level number (e.g. 0, 1, 2). Optional.
                aliases: Alternative names. Optional.
            """
            body = {"name": name}
            if level is not None:
                body["level"] = level
            if aliases:
                body["aliases"] = aliases
            return _post("/config/floor_registry", body)

        @mcp.tool()
        def ha_update_floor(floor_id: str, name: str = "", level: int = None, aliases: list = None) -> dict:
            """
            Update an existing floor.

            Args:
                floor_id: Floor ID (from ha_list_floors).
                name:     New name. Empty = keep current.
                level:    New level. None = keep current.
                aliases:  New aliases. None = keep current.
            """
            body = {}
            if name:
                body["name"] = name
            if level is not None:
                body["level"] = level
            if aliases is not None:
                body["aliases"] = aliases
            return _post(f"/config/floor_registry/{floor_id}", body)

        @mcp.tool()
        def ha_delete_floor(floor_id: str) -> dict:
            """
            Delete a floor.

            Args:
                floor_id: Floor ID (from ha_list_floors).
            """
            return _delete(f"/config/floor_registry/{floor_id}")

        # ── LABEL REGISTRY ────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_labels() -> dict:
            """List all labels in the label registry."""
            labels = _get("/config/label_registry")
            if isinstance(labels, dict):
                return labels
            return {
                "count": len(labels),
                "labels": [
                    {
                        "label_id": lb.get("label_id"),
                        "name": lb.get("name"),
                        "color": lb.get("color"),
                        "icon": lb.get("icon"),
                    }
                    for lb in labels
                ],
            }

        @mcp.tool()
        def ha_create_label(name: str, color: str = "", icon: str = "") -> dict:
            """
            Create a new label.

            Args:
                name:  Label name.
                color: Color (e.g. '#ff0000' or CSS color). Optional.
                icon:  MDI icon (e.g. 'mdi:tag'). Optional.
            """
            body = {"name": name}
            if color:
                body["color"] = color
            if icon:
                body["icon"] = icon
            return _post("/config/label_registry", body)

        @mcp.tool()
        def ha_update_label(label_id: str, name: str = "", color: str = "", icon: str = "") -> dict:
            """
            Update an existing label.

            Args:
                label_id: Label ID (from ha_list_labels).
                name:     New name. Empty = keep current.
                color:    New color. Empty = keep current.
                icon:     New icon. Empty = keep current.
            """
            body = {}
            if name:
                body["name"] = name
            if color:
                body["color"] = color
            if icon:
                body["icon"] = icon
            return _post(f"/config/label_registry/{label_id}", body)

        @mcp.tool()
        def ha_delete_label(label_id: str) -> dict:
            """
            Delete a label.

            Args:
                label_id: Label ID (from ha_list_labels).
            """
            return _delete(f"/config/label_registry/{label_id}")

        # ── ZONES ─────────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_zones() -> dict:
            """List all zone entities with their coordinates and radius."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            zones = [s for s in states if s.get("entity_id", "").startswith("zone.")]
            return {
                "count": len(zones),
                "zones": [
                    {
                        "entity_id": z.get("entity_id"),
                        "name": z.get("attributes", {}).get("friendly_name"),
                        "latitude": z.get("attributes", {}).get("latitude"),
                        "longitude": z.get("attributes", {}).get("longitude"),
                        "radius": z.get("attributes", {}).get("radius"),
                        "passive": z.get("attributes", {}).get("passive", False),
                        "icon": z.get("attributes", {}).get("icon"),
                    }
                    for z in zones
                ],
            }

        # ── DASHBOARD (LOVELACE) ──────────────────────────────────────────────

        @mcp.tool()
        def ha_list_dashboards() -> dict:
            """List all Lovelace dashboards."""
            return _get("/lovelace/dashboards")

        @mcp.tool()
        def ha_get_dashboard(dashboard_id: str = "") -> dict:
            """
            Get a Lovelace dashboard configuration.

            Args:
                dashboard_id: Dashboard slug (e.g. 'my-dashboard').
                              Empty = default dashboard.
            """
            path = f"/lovelace/config?config_key={dashboard_id}" if dashboard_id else "/lovelace/config"
            return _get(path)

        @mcp.tool()
        def ha_set_dashboard(config: dict, dashboard_id: str = "") -> dict:
            """
            Save a Lovelace dashboard configuration.

            WARNING: Overwrites the current dashboard config.

            Args:
                config:       Full Lovelace config as dict.
                dashboard_id: Dashboard slug. Empty = default dashboard.
            """
            path = f"/lovelace/config?config_key={dashboard_id}" if dashboard_id else "/lovelace/config"
            return _post(path, config)

        # ── CALENDAR ─────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_calendars() -> dict:
            """List all calendar entities."""
            result = _get("/calendars")
            if isinstance(result, dict):
                return result
            return {
                "count": len(result),
                "calendars": [
                    {"entity_id": c.get("entity_id"), "name": c.get("name")}
                    for c in result
                ],
            }

        @mcp.tool()
        def ha_get_calendar_events(entity_id: str, days: int = 7) -> dict:
            """
            Get upcoming calendar events.

            Args:
                entity_id: Calendar entity (e.g. 'calendar.thuiskalender').
                days:      How many days ahead to fetch (default 7).
            """
            now   = datetime.now(timezone.utc)
            end   = now + timedelta(days=days)
            result = _get(
                f"/calendars/{entity_id}",
                params={"start": now.isoformat(), "end": end.isoformat()},
            )
            if isinstance(result, dict) and "error" in result:
                return result
            if isinstance(result, list):
                return {"entity_id": entity_id, "count": len(result), "events": result}
            return result

        @mcp.tool()
        def ha_create_calendar_event(
            entity_id: str,
            summary: str,
            start: str,
            end: str,
            description: str = "",
            location: str = "",
        ) -> dict:
            """
            Create a calendar event.

            Args:
                entity_id:   Calendar entity (e.g. 'calendar.thuiskalender').
                summary:     Event title.
                start:       Start datetime ISO 8601 (e.g. '2025-06-01T10:00:00').
                end:         End datetime ISO 8601.
                description: Optional description.
                location:    Optional location.
            """
            data = {
                "entity_id": entity_id,
                "summary": summary,
                "start_date_time": start,
                "end_date_time": end,
            }
            if description:
                data["description"] = description
            if location:
                data["location"] = location
            return _service("calendar", "create_event", data)

        @mcp.tool()
        def ha_delete_calendar_event(entity_id: str, uid: str, recurrence_id: str = "") -> dict:
            """
            Delete a calendar event.

            Args:
                entity_id:     Calendar entity.
                uid:           Event UID (from ha_get_calendar_events).
                recurrence_id: For recurring events, the specific occurrence. Optional.
            """
            data = {"entity_id": entity_id, "uid": uid}
            if recurrence_id:
                data["recurrence_id"] = recurrence_id
            return _service("calendar", "delete_event", data)

        # ── TODO LISTS ────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_todos() -> dict:
            """List all todo list entities."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            todos = [s for s in states if s.get("entity_id", "").startswith("todo.")]
            return {
                "count": len(todos),
                "todo_lists": [
                    {
                        "entity_id": t.get("entity_id"),
                        "name": t.get("attributes", {}).get("friendly_name"),
                        "items_count": t.get("state"),
                    }
                    for t in todos
                ],
            }

        @mcp.tool()
        def ha_get_todo_items(entity_id: str, status: str = "") -> dict:
            """
            Get items from a todo list.

            Args:
                entity_id: Todo list entity (e.g. 'todo.boodschappen').
                status:    Filter by status: 'needs_action' or 'completed'. Empty = all.
            """
            data = {"entity_id": entity_id}
            if status:
                data["status"] = [status]
            result = _post("/services/todo/get_items", data, params={"return_response": "true"})
            # Response structure: {entity_id: {"items": [...]}}
            if isinstance(result, dict) and entity_id in result:
                items = result[entity_id].get("items", [])
                return {"entity_id": entity_id, "count": len(items), "items": items}
            return result

        @mcp.tool()
        def ha_add_todo_item(entity_id: str, item: str, due_date: str = "", description: str = "") -> dict:
            """
            Add an item to a todo list.

            Args:
                entity_id:   Todo list entity.
                item:        Item summary/title.
                due_date:    Optional due date (ISO 8601 date, e.g. '2025-06-01').
                description: Optional description.
            """
            data = {"entity_id": entity_id, "item": item}
            if due_date:
                data["due_date"] = due_date
            if description:
                data["description"] = description
            return _service("todo", "add_item", data)

        @mcp.tool()
        def ha_update_todo_item(
            entity_id: str,
            item: str,
            rename: str = "",
            status: str = "",
            due_date: str = "",
            description: str = "",
        ) -> dict:
            """
            Update a todo list item.

            Args:
                entity_id:   Todo list entity.
                item:        Current item name/UID to update.
                rename:      New name. Empty = keep current.
                status:      'needs_action' or 'completed'. Empty = keep current.
                due_date:    New due date. Empty = keep current.
                description: New description. Empty = keep current.
            """
            data = {"entity_id": entity_id, "item": item}
            if rename:
                data["rename"] = rename
            if status:
                data["status"] = status
            if due_date:
                data["due_date"] = due_date
            if description:
                data["description"] = description
            return _service("todo", "update_item", data)

        @mcp.tool()
        def ha_remove_todo_items(entity_id: str, items: list) -> dict:
            """
            Remove one or more items from a todo list.

            Args:
                entity_id: Todo list entity.
                items:     List of item names/UIDs to remove.
            """
            return _service("todo", "remove_item", {"entity_id": entity_id, "item": items})

        # ── AUTOMATIONS ───────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_automations() -> dict:
            """List all automations with their state (on/off) and last triggered time."""
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
                automation_id: Automation ID or full entity_id (prefix stripped automatically).
            """
            aid = automation_id.removeprefix("automation.")
            return _get(f"/config/automation/config/{aid}")

        @mcp.tool()
        def ha_set_automation(automation_id: str, config: dict) -> dict:
            """
            Create or update an automation.

            Args:
                automation_id: Automation ID (without 'automation.' prefix).
                config:        Full automation config dict (same structure as YAML).
            """
            aid = automation_id.removeprefix("automation.")
            return _post(f"/config/automation/config/{aid}", config)

        @mcp.tool()
        def ha_delete_automation(automation_id: str) -> dict:
            """
            Delete an automation.

            Args:
                automation_id: Automation ID (without 'automation.' prefix).
            """
            aid = automation_id.removeprefix("automation.")
            return _delete(f"/config/automation/config/{aid}")

        @mcp.tool()
        def ha_get_automation_traces(automation_id: str) -> dict:
            """
            Get recent execution traces for an automation (for debugging).

            Args:
                automation_id: Automation ID (without 'automation.' prefix).
            """
            aid = automation_id.removeprefix("automation.")
            return _get(f"/config/automation/trace/{aid}")

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
                script_id: Script ID (with or without 'script.' prefix).
            """
            sid = script_id.removeprefix("script.")
            return _get(f"/config/script/config/{sid}")

        @mcp.tool()
        def ha_set_script(script_id: str, config: dict) -> dict:
            """
            Create or update a script.

            Args:
                script_id: Script ID (without 'script.' prefix).
                config:    Full script config dict.
            """
            sid = script_id.removeprefix("script.")
            return _post(f"/config/script/config/{sid}", config)

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
            """List all helper entities (input_boolean, timer, counter, etc.)."""
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

        # ── SCENES & GROUPS ───────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_scenes() -> dict:
            """List all scenes."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            scenes = [s for s in states if s.get("entity_id", "").startswith("scene.")]
            return {
                "count": len(scenes),
                "scenes": [
                    {
                        "entity_id": s.get("entity_id"),
                        "friendly_name": s.get("attributes", {}).get("friendly_name"),
                    }
                    for s in scenes
                ],
            }

        @mcp.tool()
        def ha_list_groups() -> dict:
            """List all group entities."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            groups = [s for s in states if s.get("entity_id", "").startswith("group.")]
            return {
                "count": len(groups),
                "groups": [
                    {
                        "entity_id": g.get("entity_id"),
                        "friendly_name": g.get("attributes", {}).get("friendly_name"),
                        "state": g.get("state"),
                        "members": g.get("attributes", {}).get("entity_id", []),
                    }
                    for g in groups
                ],
            }

        # ── UPDATES ───────────────────────────────────────────────────────────

        @mcp.tool()
        def ha_list_updates() -> dict:
            """List all available updates (HA core, addons, HACS, etc.)."""
            states = _get("/states")
            if isinstance(states, dict):
                return states
            updates = [
                s for s in states
                if s.get("entity_id", "").startswith("update.")
                and s.get("state") == "on"
            ]
            return {
                "count": len(updates),
                "updates": [
                    {
                        "entity_id": u.get("entity_id"),
                        "name": u.get("attributes", {}).get("friendly_name"),
                        "installed_version": u.get("attributes", {}).get("installed_version"),
                        "latest_version": u.get("attributes", {}).get("latest_version"),
                        "release_url": u.get("attributes", {}).get("release_url"),
                    }
                    for u in updates
                ],
            }

        # ── LONG-TERM STATISTICS (WebSocket) ──────────────────────────────────

        from core.websocket import ha_ws_call

        @mcp.tool()
        def ha_list_statistic_ids(statistic_type: str = "") -> dict:
            """
            List all available long-term statistic IDs (sensors that HA tracks historically).

            Args:
                statistic_type: Filter by type: 'mean' (sensors with average) or
                                'sum' (sensors with cumulative total, e.g. energy).
                                Empty = all.
            """
            cmd = {"type": "recorder/list_statistic_ids"}
            if statistic_type:
                cmd["statistic_type"] = statistic_type
            result = ha_ws_call(token, url, cmd)
            if isinstance(result, dict) and "error" in result:
                return result
            if not isinstance(result, list):
                return {"error": f"Unexpected response: {result}"}
            return {
                "count": len(result),
                "statistic_ids": [
                    {
                        "statistic_id": s.get("statistic_id"),
                        "display_unit_of_measurement": s.get("display_unit_of_measurement"),
                        "mean": s.get("has_mean", False),
                        "sum": s.get("has_sum", False),
                        "name": s.get("name"),
                        "source": s.get("source"),
                    }
                    for s in result
                ],
            }

        @mcp.tool()
        def ha_get_statistics(
            statistic_ids: list,
            period: str = "hour",
            start_time: str = "",
            end_time: str = "",
            types: list = None,
        ) -> dict:
            """
            Get long-term statistics for one or more sensors.

            Args:
                statistic_ids: List of statistic IDs (from ha_list_statistic_ids),
                               e.g. ['sensor.energy_consumption', 'sensor.gas_usage'].
                period:        Aggregation period: '5minute', 'hour', 'day', 'week', 'month'.
                               Default 'hour'.
                start_time:    Start of range, ISO 8601 (e.g. '2025-01-01T00:00:00+00:00').
                               Empty = 24 hours ago.
                end_time:      End of range, ISO 8601. Empty = now.
                types:         Which values to include: any of 'mean', 'min', 'max', 'sum',
                               'state', 'change'. Default: all available.
            """
            if not start_time:
                start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            if not end_time:
                end_time = datetime.now(timezone.utc).isoformat()

            cmd = {
                "type": "recorder/statistics_during_period",
                "statistic_ids": statistic_ids,
                "period": period,
                "start_time": start_time,
                "end_time": end_time,
                "units": {},
                "types": types or ["mean", "min", "max", "sum", "state", "change"],
            }
            result = ha_ws_call(token, url, cmd)
            if isinstance(result, dict) and "error" in result:
                return result
            # result is {statistic_id: [{start, end, mean, min, max, sum, ...}, ...]}
            summary = {}
            for sid, data_points in (result or {}).items():
                summary[sid] = {
                    "count": len(data_points),
                    "data": data_points,
                }
            return {"period": period, "statistics": summary}

        log.info("[HomeAssistant] Core HA tools registered")
