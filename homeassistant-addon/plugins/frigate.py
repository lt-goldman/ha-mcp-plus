"""
Frigate plugin — auto-activated when ccab4aaf_frigate-proxy is running.
"""

import httpx
import logging
import time
from typing import Optional
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.frigate")


class FrigatePlugin(BasePlugin):
    NAME          = "Frigate"
    DESCRIPTION   = "Access Frigate camera events, recordings, stats and object detection"
    ADDON_SLUG    = "frigate"
    INTERNAL_PORT = 5000
    CONFIG_KEY    = ""  # No token needed

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url

        def _get(path: str, params: dict = None) -> dict:
            full_url = f"{url}{path}"
            try:
                r = httpx.get(full_url, params=params or {}, timeout=10)
                if not r.is_success:
                    log.error(f"[Frigate] HTTP {r.status_code} for GET {path}: {r.text[:200]}")
                    return {"error": f"HTTP {r.status_code}"}
                return r.json()
            except httpx.ConnectError:
                log.error(f"[Frigate] Connection refused at {url} — is Frigate running?")
                return {"error": f"Cannot connect to Frigate at {url}"}
            except httpx.TimeoutException:
                log.error(f"[Frigate] Timeout for GET {path}")
                return {"error": f"Timeout connecting to Frigate at {url}"}
            except Exception as e:
                log.error(f"[Frigate] Unexpected error for GET {path}: {e}")
                return {"error": str(e)}

        @mcp.tool()
        def frigate_health() -> dict:
            """Check Frigate connectivity and version."""
            try:
                r = httpx.get(f"{url}/api/version", timeout=5)
                if not r.is_success:
                    log.error(f"[Frigate] Health check failed: HTTP {r.status_code}")
                    return {"connected": False, "error": f"HTTP {r.status_code}"}
                log.debug(f"[Frigate] Health check OK at {url}")
                return {"connected": True, "version": r.text.strip()}
            except httpx.ConnectError:
                log.error(f"[Frigate] Connection refused at {url} — is Frigate running?")
                return {"connected": False, "error": f"Cannot connect to Frigate at {url}"}
            except httpx.TimeoutException:
                log.error(f"[Frigate] Health check timeout at {url}")
                return {"connected": False, "error": f"Timeout at {url}"}
            except Exception as e:
                log.error(f"[Frigate] Health check error: {e}")
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def frigate_get_cameras() -> dict:
            """List all configured Frigate cameras with detection settings."""
            data = _get("/api/config")
            if "error" in data:
                return data
            cameras = data.get("cameras", {})
            return {
                "count": len(cameras),
                "cameras": {
                    name: {
                        "enabled": cfg.get("enabled", True),
                        "detect": cfg.get("detect", {}).get("enabled", True),
                        "objects": cfg.get("objects", {}).get("track", []),
                        "record": cfg.get("record", {}).get("enabled", False),
                    }
                    for name, cfg in cameras.items()
                },
            }

        @mcp.tool()
        def frigate_get_events(
            camera: Optional[str] = None,
            label: Optional[str] = None,
            limit: int = 20,
            has_snapshot: Optional[bool] = None,
        ) -> dict:
            """
            Get Frigate detection events.

            Args:
                camera: Filter by camera name (e.g. 'oprit', 'voordeur').
                label: Filter by object label ('person', 'car', 'dog', etc.).
                limit: Max events to return (default 20).
                has_snapshot: Only events with/without snapshot.
            """
            params = {"limit": limit}
            if camera:      params["camera"] = camera
            if label:       params["label"] = label
            if has_snapshot is not None: params["has_snapshot"] = int(has_snapshot)

            data = _get("/api/events", params)
            if "error" in data:
                return data
            events = data if isinstance(data, list) else []
            return {
                "count": len(events),
                "events": [
                    {
                        "id": e.get("id"),
                        "camera": e.get("camera"),
                        "label": e.get("label"),
                        "score": round(e.get("score", 0) * 100, 1),
                        "start_time": e.get("start_time"),
                        "has_snapshot": e.get("has_snapshot"),
                        "snapshot_url": f"{url}/api/events/{e.get('id')}/snapshot.jpg" if e.get("has_snapshot") else None,
                        "clip_url": f"{url}/api/events/{e.get('id')}/clip.mp4" if e.get("has_clip") else None,
                    }
                    for e in events
                ],
            }

        @mcp.tool()
        def frigate_get_stats() -> dict:
            """Get Frigate system stats: detector performance, camera FPS, CPU/GPU."""
            return _get("/api/stats")

        @mcp.tool()
        def frigate_get_event_counts(
            camera: Optional[str] = None,
            label: Optional[str] = None,
            hours: int = 24,
        ) -> dict:
            """
            Get event counts grouped by camera and label for the last N hours.
            Useful for trend analysis.

            Args:
                camera: Filter by camera name.
                label: Filter by object label.
                hours: Look back this many hours (default 24).
            """
            after = int(time.time()) - hours * 3600
            params = {"after": after, "limit": 1000}
            if camera: params["camera"] = camera
            if label:  params["label"] = label

            data = _get("/api/events", params)
            if "error" in data:
                return data
            events = data if isinstance(data, list) else []
            counts: dict = {}
            for e in events:
                key = f"{e.get('camera')} / {e.get('label')}"
                counts[key] = counts.get(key, 0) + 1
            return {
                "period_hours": hours,
                "total_events": len(events),
                "by_camera_label": dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)),
            }
