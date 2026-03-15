"""
Grafana plugin — auto-activated when a0d7b954_grafana is running.
"""

import httpx
from typing import Optional, List
from core.plugin_base import BasePlugin, PluginConfig


class GrafanaPlugin(BasePlugin):
    NAME          = "Grafana"
    DESCRIPTION   = "Create and manage Grafana dashboards and panels via the REST API"
    ADDON_SLUG    = "a0d7b954_grafana"
    INTERNAL_PORT = 3000
    CONFIG_KEY    = "grafana_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url   = cfg.url
        token = cfg.token
        bucket = cfg.extra.get("influx_bucket", "homeassistant")

        def _headers():
            h = {"Content-Type": "application/json"}
            if token:
                h["Authorization"] = f"Bearer {token}"
            return h

        def _get(path: str) -> dict:
            try:
                r = httpx.get(f"{url}{path}", headers=_headers(), timeout=10)
                return r.json()
            except Exception as e:
                return {"error": str(e)}

        def _post(path: str, data: dict) -> dict:
            try:
                r = httpx.post(f"{url}{path}", headers=_headers(), json=data, timeout=15)
                return r.json()
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def grafana_health() -> dict:
            """Check Grafana connectivity."""
            return _get("/api/health")

        @mcp.tool()
        def grafana_get_datasources() -> dict:
            """List all Grafana datasources (InfluxDB, Prometheus, etc.)."""
            data = _get("/api/datasources")
            if isinstance(data, list):
                return {"datasources": [{"id": d.get("id"), "uid": d.get("uid"), "name": d.get("name"), "type": d.get("type")} for d in data]}
            return data

        @mcp.tool()
        def grafana_list_dashboards(query: str = "") -> dict:
            """List all Grafana dashboards."""
            path = "/api/search?type=dash-db"
            if query:
                path += f"&query={query}"
            data = _get(path)
            if isinstance(data, list):
                return {"count": len(data), "dashboards": [{"uid": d.get("uid"), "title": d.get("title"), "id": d.get("id")} for d in data]}
            return data

        @mcp.tool()
        def grafana_create_dashboard(title: str, tags: Optional[List[str]] = None) -> dict:
            """
            Create a new empty Grafana dashboard.

            Args:
                title: Dashboard title.
                tags: Optional list of tags.

            Returns the dashboard UID for use with grafana_add_panel().
            """
            payload = {
                "dashboard": {
                    "title": title,
                    "tags": tags or ["ha-mcp-plus"],
                    "timezone": "browser",
                    "schemaVersion": 39,
                    "panels": [],
                    "time": {"from": "now-24h", "to": "now"},
                    "refresh": "30s",
                },
                "overwrite": False,
                "message": "Created by ha-mcp-plus",
            }
            result = _post("/api/dashboards/db", payload)
            return {
                "success": result.get("status") == "success",
                "uid": result.get("uid"),
                "url": result.get("url"),
                "title": title,
            }

        @mcp.tool()
        def grafana_add_panel(
            dashboard_uid: str,
            title: str,
            entity_ids: List[str],
            panel_type: str = "timeseries",
            range_hours: int = 24,
            aggregation: str = "mean",
            window: str = "5m",
            unit: str = "short",
            flux_query: Optional[str] = None,
        ) -> dict:
            """
            Add a panel to a Grafana dashboard for one or more HA entities.
            Automatically builds the InfluxDB Flux query unless flux_query is provided.

            Args:
                dashboard_uid: Dashboard UID (from grafana_create_dashboard or grafana_list_dashboards).
                title: Panel title.
                entity_ids: List of HA entity IDs to plot.
                panel_type: 'timeseries' (default), 'gauge', 'stat', 'bar'.
                range_hours: Time range in hours (default 24).
                aggregation: 'mean', 'last', 'max', 'min' (default 'mean').
                window: Aggregation window (default '5m').
                unit: Grafana unit ('celsius', 'watt', 'percent', 'short').
                flux_query: Optional pre-built Flux query (overrides auto-build).
            """
            # Get current dashboard
            dash_resp = _get(f"/api/dashboards/uid/{dashboard_uid}")
            dash = dash_resp.get("dashboard", {})
            panels = dash.get("panels", [])
            next_id = max((p.get("id", 0) for p in panels), default=0) + 1

            # Build Flux query if not provided
            if not flux_query:
                filter_clause = " or ".join([f'r["entity_id"] == "{e}"' for e in entity_ids])
                flux_query = f"""from(bucket: "{bucket}")
  |> range(start: -{range_hours}h)
  |> filter(fn: (r) => {filter_clause})
  |> filter(fn: (r) => r["_field"] == "value")
  |> aggregateWindow(every: {window}, fn: {aggregation}, createEmpty: false)"""

            panel = {
                "id": next_id,
                "title": title,
                "type": panel_type,
                "gridPos": {"h": 8, "w": 12, "x": (next_id - 1) % 2 * 12, "y": (next_id - 1) // 2 * 8},
                "datasource": {"type": "influxdb"},
                "targets": [{"refId": "A", "query": flux_query, "queryType": "flux"}],
                "fieldConfig": {
                    "defaults": {
                        "unit": unit,
                        "custom": {"lineWidth": 2, "fillOpacity": 10, "spanNulls": True},
                    }
                },
                "options": {"tooltip": {"mode": "multi"}, "legend": {"displayMode": "table", "placement": "bottom"}},
            }

            panels.append(panel)
            dash["panels"] = panels
            result = _post("/api/dashboards/db", {"dashboard": dash, "overwrite": True, "message": f"Added panel '{title}' via ha-mcp-plus"})

            return {
                "success": result.get("status") == "success",
                "panel_id": next_id,
                "title": title,
                "embed_url": f"{url}/d-solo/{dashboard_uid}?panelId={next_id}&from=now-{range_hours}h&to=now&kiosk",
            }
