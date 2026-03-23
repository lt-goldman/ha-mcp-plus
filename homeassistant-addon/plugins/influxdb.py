"""
InfluxDB plugin — auto-activated when influxdb is running.
Supports both InfluxDB v1 (InfluxQL) and v2 (Flux), auto-detected at startup.
"""

import httpx
import logging
from typing import Optional, List
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.influxdb")


class InfluxDBPlugin(BasePlugin):
    NAME          = "InfluxDB"
    DESCRIPTION   = "Query measurements, find entity data, build Grafana-ready queries"
    ADDON_SLUG    = "influxdb"
    INTERNAL_PORT = 8086
    CONFIG_KEY    = "influx_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url      = cfg.url
        token    = cfg.token
        org      = cfg.extra.get("influx_org", "homeassistant")
        bucket   = cfg.extra.get("influx_bucket", "homeassistant")
        username = cfg.extra.get("influx_username", "")
        password = cfg.extra.get("influx_password", "")

        # ── Version detection ──────────────────────────────────────
        _version = None

        def _detect_version() -> str:
            nonlocal _version
            if _version:
                return _version
            try:
                r = httpx.get(f"{url}/health", timeout=5)
                v = r.json().get("version", "")
                _version = "v1" if v.startswith("1.") else "v2"
                log.info(f"[InfluxDB] Detected version: {_version} ({v})")
            except Exception as e:
                log.warning(f"[InfluxDB] Version detection failed, defaulting to v1: {e}")
                _version = "v1"
            return _version

        # ── v1 query (InfluxQL) ────────────────────────────────────
        def _query_v1(influxql: str, database: str = None) -> dict:
            db = database or bucket
            params = {"db": db, "q": influxql}
            if username:
                params["u"] = username
                params["p"] = password
            try:
                r = httpx.get(
                    f"{url}/query",
                    params=params,
                    timeout=15,
                )
                if not r.is_success:
                    log.error(f"[InfluxDB v1] Query failed: HTTP {r.status_code} — {r.text[:300]}")
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                data = r.json()
                results = data.get("results", [{}])
                if results and "error" in results[0]:
                    return {"error": results[0]["error"]}
                series = results[0].get("series", []) if results else []
                rows = []
                for s in series:
                    cols = s.get("columns", [])
                    for val in s.get("values", []):
                        rows.append(dict(zip(cols, val)))
                return {"rows": rows[:200], "total": len(rows), "series": [s.get("name") for s in series]}
            except httpx.ConnectError:
                return {"error": f"Cannot connect to InfluxDB at {url}"}
            except httpx.TimeoutException:
                return {"error": f"Timeout connecting to InfluxDB at {url}"}
            except Exception as e:
                return {"error": str(e)}

        # ── v2 query (Flux) ────────────────────────────────────────
        def _query_v2(flux: str) -> dict:
            try:
                r = httpx.post(
                    f"{url}/api/v2/query",
                    headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
                    json={"query": flux, "type": "flux", "org": org},
                    timeout=15,
                )
                if not r.is_success:
                    log.error(f"[InfluxDB v2] Query failed: HTTP {r.status_code} — {r.text[:300]}")
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
                lines = [l for l in r.text.splitlines() if l and not l.startswith("#")]
                if not lines:
                    return {"rows": [], "raw": r.text[:300]}
                headers = lines[0].split(",")
                rows = [dict(zip(headers, l.split(","))) for l in lines[1:] if l]
                return {"rows": rows[:200], "total": len(rows)}
            except httpx.ConnectError:
                return {"error": f"Cannot connect to InfluxDB at {url}"}
            except httpx.TimeoutException:
                return {"error": f"Timeout connecting to InfluxDB at {url}"}
            except Exception as e:
                return {"error": str(e)}

        def _query_auto(influxql: str, flux: str) -> dict:
            """Run the right query based on detected version."""
            if _detect_version() == "v1":
                return _query_v1(influxql)
            return _query_v2(flux)

        # ── Tools ──────────────────────────────────────────────────

        @mcp.tool()
        def influxdb_health() -> dict:
            """Check InfluxDB connectivity and version."""
            try:
                r = httpx.get(f"{url}/health", timeout=5)
                if not r.is_success:
                    return {"connected": False, "error": f"HTTP {r.status_code}"}
                data = r.json()
                _detect_version()  # cache version
                return data
            except httpx.ConnectError:
                return {"connected": False, "error": f"Cannot connect to InfluxDB at {url}"}
            except httpx.TimeoutException:
                return {"connected": False, "error": f"Timeout at {url}"}
            except Exception as e:
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def influxdb_list_measurements(bucket_name: Optional[str] = None) -> dict:
            """List all measurements in the InfluxDB bucket/database."""
            b = bucket_name or bucket
            return _query_auto(
                influxql=f'SHOW MEASUREMENTS ON "{b}"',
                flux=f'import "influxdata/influxdb/schema"\nschema.measurements(bucket: "{b}")',
            )

        @mcp.tool()
        def influxdb_find_entity(entity_id: str) -> dict:
            """
            Find the InfluxDB measurement and field for a specific HA entity.
            Returns everything needed to build a Grafana panel query.

            Args:
                entity_id: HA entity ID (e.g. 'sensor.temperatuur').
            """
            if _detect_version() == "v1":
                # In HA+InfluxDB v1, entity_id is a tag; measurement is the unit
                result = _query_v1(
                    f'SELECT * FROM /.*/ WHERE "entity_id" = \'{entity_id}\' LIMIT 1',
                    database=bucket,
                )
                if result.get("rows"):
                    row = result["rows"][0]
                    measurement = result.get("series", ["unknown"])[0]
                    query_ready = (
                        f'SELECT mean("value") FROM "{measurement}" '
                        f'WHERE "entity_id" = \'{entity_id}\' '
                        f'AND $timeFilter GROUP BY time(5m) fill(null)'
                    )
                    return {
                        "found": True,
                        "entity_id": entity_id,
                        "measurement": measurement,
                        "last_value": row.get("value"),
                        "influxql_query": query_ready,
                        "version": "v1",
                    }
                return {"found": False, "entity_id": entity_id, "hint": "No data in last hour", "version": "v1"}
            else:
                flux = f"""from(bucket: "{bucket}")
  |> range(start: -1h)
  |> filter(fn: (r) => r["entity_id"] == "{entity_id}")
  |> first()
  |> limit(n: 1)"""
                result = _query_v2(flux)
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
                        "version": "v2",
                    }
                return {"found": False, "entity_id": entity_id, "hint": "No data in last hour", "version": "v2"}

        @mcp.tool()
        def influxdb_query(query: str) -> dict:
            """
            Execute a raw query against InfluxDB.
            Use InfluxQL syntax for v1 (e.g. SELECT mean("value") FROM "°C" WHERE ...),
            or Flux syntax for v2 (e.g. from(bucket:...) |> ...).
            The correct endpoint is chosen automatically based on the detected version.

            Args:
                query: InfluxQL query (v1) or Flux query (v2).
            """
            if _detect_version() == "v1":
                return _query_v1(query)
            return _query_v2(query)

        @mcp.tool()
        def influxdb_build_grafana_query(
            entity_ids: List[str],
            range_hours: int = 24,
            aggregation: str = "mean",
            window: str = "5m",
        ) -> dict:
            """
            Build a query for one or more HA entities, ready for a Grafana panel.
            Returns both InfluxQL (v1) and Flux (v2) versions.

            Args:
                entity_ids: List of HA entity IDs to include.
                range_hours: Time range in hours (default 24).
                aggregation: 'mean', 'last', 'max', 'min' (default 'mean').
                window: Aggregation window (default '5m').
            """
            version = _detect_version()

            # InfluxQL (v1)
            where = " OR ".join([f'"entity_id" = \'{e}\'' for e in entity_ids])
            influxql = (
                f'SELECT {aggregation}("value") FROM /.*/ '
                f'WHERE ({where}) AND $timeFilter '
                f'GROUP BY time({window}), "entity_id" fill(null)'
            )

            # Flux (v2)
            filter_clause = " or ".join([f'r["entity_id"] == "{e}"' for e in entity_ids])
            flux = f"""from(bucket: "{bucket}")
  |> range(start: -{range_hours}h)
  |> filter(fn: (r) => {filter_clause})
  |> filter(fn: (r) => r["_field"] == "value")
  |> aggregateWindow(every: {window}, fn: {aggregation}, createEmpty: false)
  |> yield(name: "{aggregation}")"""

            return {
                "detected_version": version,
                "recommended_query": influxql if version == "v1" else flux,
                "influxql_query": influxql,
                "flux_query": flux,
                "entity_ids": entity_ids,
                "hint": "Pass recommended_query to grafana_add_panel.",
            }
