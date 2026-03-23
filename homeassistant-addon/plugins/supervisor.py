"""
Supervisor tools — control HA add-ons, check config, restart HA.
Dangerous operations (restart, stop) go through SafetyGuard.
"""

import httpx
import logging
import os
from typing import Optional
from core.plugin_base import BasePlugin, PluginConfig
from core.safety import plan_supervisor_restart_ha, plan_addon_stop

log = logging.getLogger("ha-mcp-plus.supervisor")


class SupervisorPlugin(BasePlugin):
    NAME          = "Supervisor"
    DESCRIPTION   = "Control HA addons and system (dangerous ops require explicit execute=True)"
    ADDON_SLUG    = ""   # Always active
    INTERNAL_PORT = 0
    CONFIG_KEY    = ""

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        supervisor_url = "http://supervisor"

        def _get_token() -> str:
            for t in [
                os.environ.get("SUPERVISOR_TOKEN"),
                os.environ.get("HASSIO_TOKEN"),
            ]:
                if t:
                    return t
            for path in [
                "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
                "/run/s6/container_environment/SUPERVISOR_TOKEN",
            ]:
                try:
                    with open(path) as f:
                        t = f.read().strip()
                    if t:
                        return t
                except FileNotFoundError:
                    pass
            try:
                with open("/proc/1/environ", "rb") as f:
                    for part in f.read().split(b"\x00"):
                        if part.startswith(b"SUPERVISOR_TOKEN="):
                            t = part.split(b"=", 1)[1].decode().strip()
                            if t:
                                return t
            except Exception:
                pass
            log.warning("[Supervisor] No SUPERVISOR_TOKEN found")
            return ""

        def _headers() -> dict:
            # Supervisor API uses X-Supervisor-Token, not Authorization: Bearer
            return {"X-Supervisor-Token": _get_token(), "Content-Type": "application/json"}

        def _sup(method: str, path: str, json: dict = None) -> dict:
            full_url = f"{supervisor_url}{path}"
            try:
                r = httpx.request(method, full_url, headers=_headers(), json=json, timeout=30)
                if not r.is_success:
                    log.error(f"[Supervisor] HTTP {r.status_code} for {method} {path}: {r.text[:200]}")
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
                data = r.json()
                return data.get("data", data)
            except httpx.ConnectError:
                log.error(f"[Supervisor] Cannot connect to {supervisor_url}")
                return {"error": "Cannot connect to Supervisor API"}
            except httpx.TimeoutException:
                return {"error": f"Timeout for {method} {path}"}
            except Exception as e:
                log.error(f"[Supervisor] Unexpected error for {method} {path}: {e}")
                return {"error": str(e)}

        # ── SAFE READ TOOLS ───────────────────────────────────────────────

        @mcp.tool()
        def supervisor_list_addons() -> dict:
            """List all installed HA add-ons with their state and version."""
            data = _sup("GET", "/addons")
            addons = data.get("addons", data) if isinstance(data, dict) else data
            return {
                "count": len(addons),
                "addons": [
                    {
                        "slug": a.get("slug"),
                        "name": a.get("name"),
                        "state": a.get("state"),
                        "version": a.get("version"),
                        "update_available": a.get("update_available", False),
                    }
                    for a in (addons if isinstance(addons, list) else [])
                ],
            }

        @mcp.tool()
        def supervisor_health() -> dict:
            """Check Supervisor API connectivity and token availability."""
            token = _get_token()
            return {
                "SUPERVISOR_TOKEN_set": bool(os.environ.get("SUPERVISOR_TOKEN")),
                "HASSIO_TOKEN_set": bool(os.environ.get("HASSIO_TOKEN")),
                "token_length": len(token),
                "ping": _sup("GET", "/info"),
            }

        @mcp.tool()
        def supervisor_addon_info(slug: str) -> dict:
            """Get detailed info for a specific add-on including network/port config."""
            return _sup("GET", f"/addons/{slug}/info")

        @mcp.tool()
        def supervisor_addon_logs(slug: str) -> dict:
            """Get recent logs from an add-on."""
            try:
                r = httpx.get(f"{supervisor_url}/addons/{slug}/logs", headers=_headers(), timeout=10)
                return {"slug": slug, "logs": r.text[-3000:]}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def supervisor_check_config() -> dict:
            """Check Home Assistant configuration for errors before restarting."""
            return _sup("POST", "/core/check")

        @mcp.tool()
        def supervisor_system_info() -> dict:
            """Get HA system info: version, arch, machine, timezone."""
            return _sup("GET", "/info")

        @mcp.tool()
        def supervisor_reload_core() -> dict:
            """
            Reload HA configuration (templates, automations etc.) WITHOUT full restart.
            Much safer than a full restart — use this after configuration.yaml changes.
            """
            return _sup("POST", "/core/reload")

        @mcp.tool()
        def supervisor_addon_start(slug: str) -> dict:
            """Start a stopped add-on."""
            return _sup("POST", f"/addons/{slug}/start")

        @mcp.tool()
        def supervisor_addon_restart(slug: str) -> dict:
            """Restart an add-on."""
            return _sup("POST", f"/addons/{slug}/restart")

        # ── GUARDED DANGEROUS TOOLS ───────────────────────────────────────

        @mcp.tool()
        def supervisor_restart_ha(execute: bool = False) -> dict:
            """
            Restart Home Assistant Core.

            CRITICAL RISK — HA will be unavailable for 30-90 seconds.
            Shows full safety analysis first.
            Set execute=True only after reviewing the plan.

            Tip: Use supervisor_reload_core() instead if you only need to
            activate configuration.yaml changes — no downtime.

            Args:
                execute: False (default) = show plan only. True = restart.
            """
            plan = plan_supervisor_restart_ha()

            if not execute:
                return {
                    "status": "PLAN_READY",
                    "message": "HA is nog NIET herstart. Bekijk het plan.",
                    "plan": plan.render(),
                    "safer_alternative": "supervisor_reload_core() herlaadt de config zonder herstart.",
                    "next_step": "Roep deze tool opnieuw aan met execute=True als je echt wilt herstarten.",
                }

            log.warning("[Supervisor] HA Core restart initiated by user request")
            result = _sup("POST", "/core/restart")
            return {
                "success": True,
                "message": "HA herstart gestart. Verbinding wordt verbroken.",
                "result": result,
                "recovery": "HA is normaal na 30-90 seconden weer beschikbaar.",
            }

        @mcp.tool()
        def supervisor_addon_stop(slug: str, execute: bool = False) -> dict:
            """
            Stop a running add-on.

            Shows safety analysis before stopping.
            Set execute=True only after reviewing the plan.

            Args:
                slug: Add-on slug (e.g. 'a0d7b954_nodered').
                execute: False (default) = show plan only. True = stop.
            """
            # Get addon name for the plan
            info = _sup("GET", f"/addons/{slug}/info")
            name = info.get("name", slug) if isinstance(info, dict) else slug

            plan = plan_addon_stop(slug, name)

            if not execute:
                return {
                    "status": "PLAN_READY",
                    "message": f"Add-on '{name}' is nog NIET gestopt. Bekijk het plan.",
                    "plan": plan.render(),
                    "next_step": "Roep deze tool opnieuw aan met execute=True als je akkoord gaat.",
                }

            log.warning(f"[Supervisor] Add-on '{name}' ({slug}) stopped by user request")
            result = _sup("POST", f"/addons/{slug}/stop")
            return {
                "success": True,
                "message": f"Add-on '{name}' gestopt.",
                "rollback": f"Herstart via supervisor_addon_start(slug='{slug}')",
                "result": result,
            }
