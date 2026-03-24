"""
Grafana plugin — auto-activated when a0d7b954_grafana is running.
"""

import httpx
import logging
from typing import Optional, List
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.grafana")


class GrafanaPlugin(BasePlugin):
    NAME          = "Grafana"
    DESCRIPTION   = "Create and manage Grafana dashboards and panels via the REST API"
    ADDON_SLUG    = "grafana"
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
            full_url = f"{url}{path}"
            try:
                r = httpx.get(full_url, headers=_headers(), timeout=10)
                if not r.is_success:
                    log.error(f"[Grafana] HTTP {r.status_code} for GET {path}: {r.text[:200]}")
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
                return r.json()
            except httpx.ConnectError:
                log.error(f"[Grafana] Connection refused at {url} — is Grafana running?")
                return {"error": f"Cannot connect to Grafana at {url}"}
            except httpx.TimeoutException:
                log.error(f"[Grafana] Timeout for GET {path}")
                return {"error": f"Timeout connecting to Grafana at {url}"}
            except Exception as e:
                log.error(f"[Grafana] Unexpected error for GET {path}: {e}")
                return {"error": str(e)}

        def _post(path: str, data: dict) -> dict:
            full_url = f"{url}{path}"
            try:
                r = httpx.post(full_url, headers=_headers(), json=data, timeout=15)
                if not r.is_success:
                    log.error(f"[Grafana] HTTP {r.status_code} for POST {path}: {r.text[:200]}")
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
                return r.json()
            except httpx.ConnectError:
                log.error(f"[Grafana] Connection refused at {url} — is Grafana running?")
                return {"error": f"Cannot connect to Grafana at {url}"}
            except httpx.TimeoutException:
                log.error(f"[Grafana] Timeout for POST {path}")
                return {"error": f"Timeout connecting to Grafana at {url}"}
            except Exception as e:
                log.error(f"[Grafana] Unexpected error for POST {path}: {e}")
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

        def _get_influxdb_datasource() -> Optional[dict]:
            """Return the first InfluxDB datasource from Grafana, or None."""
            data = _get("/api/datasources")
            if not isinstance(data, list):
                return None
            for ds in data:
                if ds.get("type") == "influxdb":
                    return ds
            return None

        def _influxdb_is_flux(ds: dict) -> bool:
            """Return True if the datasource is configured for Flux (v2), False for InfluxQL (v1)."""
            return ds.get("jsonData", {}).get("version") == "Flux"

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
            influxql_query: Optional[str] = None,
        ) -> dict:
            """
            Add a panel to a Grafana dashboard for one or more HA entities.
            Auto-detects InfluxDB v1 (InfluxQL) or v2 (Flux) from the Grafana datasource config.
            Pass flux_query or influxql_query to override auto-build.

            Args:
                dashboard_uid: Dashboard UID (from grafana_create_dashboard or grafana_list_dashboards).
                title: Panel title.
                entity_ids: List of HA entity IDs to plot (without domain, e.g. 'power_infra').
                panel_type: 'timeseries' (default), 'gauge', 'stat', 'bar'.
                range_hours: Time range in hours (default 24).
                aggregation: 'mean', 'last', 'max', 'min' (default 'mean').
                window: Aggregation window (default '5m').
                unit: Grafana unit ('celsius', 'watt', 'percent', 'short').
                flux_query: Optional pre-built Flux query for InfluxDB v2 (overrides auto-build).
                influxql_query: Optional pre-built InfluxQL query for InfluxDB v1 (overrides auto-build).
            """
            # Get current dashboard
            dash_resp = _get(f"/api/dashboards/uid/{dashboard_uid}")
            if "error" in dash_resp:
                return dash_resp
            dash = dash_resp.get("dashboard", {})
            panels = dash.get("panels", [])
            next_id = max((p.get("id", 0) for p in panels), default=0) + 1

            # Detect datasource version
            ds = _get_influxdb_datasource()
            ds_ref = {"type": "influxdb", "uid": ds["uid"]} if ds else {"type": "influxdb"}
            use_flux = _influxdb_is_flux(ds) if ds else False

            # Build query and target
            if influxql_query or (not flux_query and not use_flux):
                # InfluxQL (v1) path
                if not influxql_query:
                    # Strip domain prefix from entity_ids (HA stores object_id in InfluxDB)
                    object_ids = [e.split(".", 1)[-1] if "." in e else e for e in entity_ids]
                    where_clause = " OR ".join([f'"entity_id" = \'{eid}\'' for eid in object_ids])
                    influxql_query = (
                        f'SELECT {aggregation}("value") FROM /.*/ '
                        f'WHERE ({where_clause}) AND $timeFilter '
                        f'GROUP BY time($__interval), "entity_id" fill(null)'
                    )
                target = {
                    "refId": "A",
                    "rawQuery": True,
                    "query": influxql_query,
                    "resultFormat": "time_series",
                    "datasource": ds_ref,
                }
            else:
                # Flux (v2) path
                if not flux_query:
                    filter_clause = " or ".join([f'r["entity_id"] == "{e}"' for e in entity_ids])
                    flux_query = (
                        f'from(bucket: "{bucket}")\n'
                        f'  |> range(start: -{range_hours}h)\n'
                        f'  |> filter(fn: (r) => {filter_clause})\n'
                        f'  |> filter(fn: (r) => r["_field"] == "value")\n'
                        f'  |> aggregateWindow(every: {window}, fn: {aggregation}, createEmpty: false)'
                    )
                target = {
                    "refId": "A",
                    "query": flux_query,
                    "queryType": "flux",
                    "datasource": ds_ref,
                }

            panel = {
                "id": next_id,
                "title": title,
                "type": panel_type,
                "gridPos": {"h": 8, "w": 12, "x": (next_id - 1) % 2 * 12, "y": (next_id - 1) // 2 * 8},
                "datasource": ds_ref,
                "targets": [target],
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
                "query_type": "flux" if (flux_query or use_flux) and not influxql_query else "influxql",
                "embed_url": f"{url}/d-solo/{dashboard_uid}?panelId={next_id}&from=now-{range_hours}h&to=now&kiosk",
            }
