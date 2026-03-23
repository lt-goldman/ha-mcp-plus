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

        ha_rest_url = "http://homeassistant"
        ha_token = cfg.extra.get("ha_token", "").strip()

        def _get_token() -> tuple[str, str]:
            """Returns (token, base_url) — prefers direct Supervisor, falls back to HA REST proxy."""
            # 1. SUPERVISOR_TOKEN / HASSIO_TOKEN from env
            sup = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HASSIO_TOKEN", "")
            if sup:
                return sup, supervisor_url
            # 2. s6 container env files
            for path in [
                "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
                "/run/s6/container_environment/SUPERVISOR_TOKEN",
            ]:
                try:
                    with open(path) as f:
                        t = f.read().strip()
                    if t:
                        return t, supervisor_url
                except FileNotFoundError:
                    pass
            # 3. /proc/1/environ
            try:
                with open("/proc/1/environ", "rb") as f:
                    for part in f.read().split(b"\x00"):
                        if part.startswith(b"SUPERVISOR_TOKEN="):
                            t = part.split(b"=", 1)[1].decode().strip()
                            if t:
                                return t, supervisor_url
            except Exception:
                pass
            # 4. HA REST proxy via ha_token (long-lived HA admin token)
            ha_rest = ha_token or os.environ.get("HA_REST_TOKEN", "")
            if ha_rest:
                log.info("[Supervisor] Using HA REST proxy (no SUPERVISOR_TOKEN found)")
                return ha_rest, f"{ha_rest_url}/api/hassio"
            log.warning("[Supervisor] No token available — all Supervisor calls will fail")
            return "", supervisor_url

        def _sup(method: str, path: str, json: dict = None) -> dict:
            token, base = _get_token()
            if not token:
                return {"error": "No Supervisor token or ha_token configured"}
            full_url = f"{base}{path}"
            try:
                r = httpx.request(
                    method, full_url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=json, timeout=30,
                )
                if not r.is_success:
                    log.error(f"[Supervisor] HTTP {r.status_code} for {method} {path}: {r.text[:200]}")
                    return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
                data = r.json()
                return data.get("data", data)
            except httpx.ConnectError:
                log.error(f"[Supervisor] Cannot connect to {full_url}")
                return {"error": f"Cannot connect to {full_url}"}
            except httpx.TimeoutException:
                log.error(f"[Supervisor] Timeout for {method} {path}")
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
            token, base = _get_token()
            via_proxy = base != supervisor_url
            return {
                "SUPERVISOR_TOKEN_set": bool(os.environ.get("SUPERVISOR_TOKEN")),
                "HASSIO_TOKEN_set": bool(os.environ.get("HASSIO_TOKEN")),
                "ha_token_configured": bool(ha_token or os.environ.get("HA_REST_TOKEN")),
                "using_ha_rest_proxy": via_proxy,
                "token_length": len(token),
                "base_url": base,
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
