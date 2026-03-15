"""
InfluxDB plugin — auto-activated when a0d7b954_influxdb is running.
"""

import httpx
from typing import Optional, List
from core.plugin_base import BasePlugin, PluginConfig


class InfluxDBPlugin(BasePlugin):
    NAME          = "InfluxDB"
    DESCRIPTION   = "Query measurements, find entity data, build Grafana-ready Flux queries"
    ADDON_SLUG    = "a0d7b954_influxdb"
    INTERNAL_PORT = 8086
    CONFIG_KEY    = "influx_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url    = cfg.url
        token  = cfg.token
        org    = cfg.extra.get("influx_org", "homeassistant")
        bucket = cfg.extra.get("influx_bucket", "homeassistant")

        def _headers():
            return {"Authorization": f"Token {token}", "Content-Type": "application/json"}

        def _query(flux: str) -> dict:
            try:
                r = httpx.post(
                    f"{url}/api/v2/query",
                    headers=_headers(),
                    json={"query": flux, "type": "flux", "org": org},
                    timeout=15,
                )
                lines = [l for l in r.text.splitlines() if l and not l.startswith("#")]
                if not lines:
                    return {"rows": [], "raw": r.text[:300]}
                headers = lines[0].split(",")
                rows = [dict(zip(headers, l.split(","))) for l in lines[1:] if l]
                return {"rows": rows[:200], "total": len(rows)}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def influxdb_health() -> dict:
            """Check InfluxDB connectivity and version."""
            try:
                r = httpx.get(f"{url}/health", timeout=5)
                return r.json()
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def influxdb_list_measurements(bucket_name: Optional[str] = None) -> dict:
            """List all measurements in the InfluxDB bucket."""
            b = bucket_name or bucket
            flux = f'import "influxdata/influxdb/schema"\nschema.measurements(bucket: "{b}")'
            return _query(flux)

        @mcp.tool()
        def influxdb_find_entity(entity_id: str) -> dict:
            """
            Find the InfluxDB measurement and field for a specific HA entity.
            Returns everything needed to build a Grafana panel query.

            Args:
                entity_id: HA entity ID (e.g. 'sensor.eb100_ep14_bt10_brine_in_temp_40015').
            """
            flux = f"""from(bucket: "{bucket}")
  |> range(start: -1h)
  |> filter(fn: (r) => r["entity_id"] == "{entity_id}")
  |> first()
  |> limit(n: 1)"""
            result = _query(flux)
            if result.get("rows"):
                row = result["rows"][0]
                flux_ready = f"""from(bucket: "{bucket}")
  |> range(start: -24h)
  |> filter(fn: (r) => r["entity_id"] == "{entity_id}")
  |> filter(fn: (r) => r["_field"] == "{row.get('_field', 'value')}")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)"""
                return {
                    "found": True,
                    "entity_id": entity_id,
                    "measurement": row.get("_measurement"),
                    "field": row.get("_field"),
                    "last_value": row.get("_value"),
                    "flux_query": flux_ready,
                }
            return {"found": False, "entity_id": entity_id, "hint": "No data in last hour"}

        @mcp.tool()
        def influxdb_query(flux: str) -> dict:
            """Execute a raw Flux query against InfluxDB."""
            return _query(flux)

        @mcp.tool()
        def influxdb_build_grafana_query(
            entity_ids: List[str],
            range_hours: int = 24,
            aggregation: str = "mean",
            window: str = "5m",
        ) -> dict:
            """
            Build a Flux query for one or more HA entities, ready for a Grafana panel.

            Args:
                entity_ids: List of HA entity IDs to include.
                range_hours: Time range in hours (default 24).
                aggregation: 'mean', 'last', 'max', 'min' (default 'mean').
                window: Aggregation window (default '5m').
            """
            filter_clause = " or ".join([f'r["entity_id"] == "{e}"' for e in entity_ids])
            flux = f"""from(bucket: "{bucket}")
  |> range(start: -{range_hours}h)
  |> filter(fn: (r) => {filter_clause})
  |> filter(fn: (r) => r["_field"] == "value")
  |> aggregateWindow(every: {window}, fn: {aggregation}, createEmpty: false)
  |> yield(name: "{aggregation}")"""
            return {
                "flux_query": flux,
                "entity_ids": entity_ids,
                "hint": "Pass this to grafana_add_panel(flux_query=...) to create a panel.",
            }
