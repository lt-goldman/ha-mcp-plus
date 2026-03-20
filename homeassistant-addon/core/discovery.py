"""
Discovery engine — queries the HA Supervisor API at startup to find
which addons are installed and running, then maps them to plugins.

For each running addon it:
1. Gets the addon info (network, hostname, ports)
2. Resolves the actual configured port (may differ from default)
3. Returns a PluginConfig with the correct URL
"""

import os
import httpx
import logging
import importlib
import pkgutil
import inspect
from typing import Dict, List, Optional, Type

from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.discovery")

SUPERVISOR_URL = "http://supervisor"


def _supervisor_token() -> str:
    token = (
        os.environ.get("SUPERVISOR_TOKEN") or
        os.environ.get("HASSIO_TOKEN") or
        os.environ.get("HA_TOKEN") or
        ""
    )
    if not token:
        # Dump available env var names to help diagnose
        auth_vars = [k for k in os.environ if any(x in k.upper() for x in ("TOKEN", "SUPERVISOR", "HASSIO"))]
        log.error(
            f"No Supervisor token found in environment (tried SUPERVISOR_TOKEN, HASSIO_TOKEN, HA_TOKEN). "
            f"Auth-related env vars present: {auth_vars or 'none'}. "
            f"Ensure hassio_api: true and hassio_role: manager in config.yaml."
        )
    return token


def _headers() -> dict:
    token = _supervisor_token()
    if not token:
        return {"Content-Type": "application/json"}
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_addon_info(slug: str) -> Optional[dict]:
    """Fetch addon info from Supervisor API. Returns None if not found/running."""
    try:
        r = httpx.get(
            f"{SUPERVISOR_URL}/addons/{slug}/info",
            headers=_headers(),
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("data", {})
        if r.status_code == 404:
            log.debug(f"Addon {slug} not installed (404)")
        else:
            log.warning(f"Supervisor returned HTTP {r.status_code} for addon {slug}")
        return None
    except httpx.ConnectError:
        log.error(f"Cannot connect to Supervisor API — is this running as a HA addon?")
        return None
    except httpx.TimeoutException:
        log.error(f"Supervisor API timeout while fetching addon info for {slug}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching addon info for {slug}: {e}")
        return None


def discover_addon_url(slug: str, internal_port: int) -> Optional[str]:
    """
    Given an addon slug and its internal port, return the URL to reach it.

    HA addon hostnames are derived from the slug: replace _ with - and strip
    the repository prefix separator.
    e.g. a0d7b954_influxdb → a0d7b954-influxdb

    The actual port may differ from internal_port if the user configured a
    custom host port mapping.
    """
    info = get_addon_info(slug)
    if not info:
        return None

    state = info.get("state", "")
    if state != "started":
        log.info(f"Addon {slug} found but not running (state={state}), skipping")
        return None

    # Hostname: slug with underscores → dashes
    hostname = slug.replace("_", "-")

    # Resolve actual port from network config
    # Supervisor returns network as {"8086/tcp": 8086} or {"8086/tcp": null} for host-network
    network = info.get("network", {}) or {}
    port_key = f"{internal_port}/tcp"
    mapped_port = network.get(port_key)

    # If mapped_port is None, addon uses host network or no port mapping → use internal
    port = mapped_port if mapped_port else internal_port

    url = f"http://{hostname}:{port}"
    log.info(f"Discovered {slug} → {url}")
    return url


def load_all_plugins() -> List[Type[BasePlugin]]:
    """
    Auto-discover all plugin classes in the plugins/ directory.
    Any class that subclasses BasePlugin is automatically found.
    """
    import plugins as plugins_pkg

    classes = []
    for _, module_name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
        module = importlib.import_module(f"plugins.{module_name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BasePlugin)
                and obj is not BasePlugin
                and obj.ADDON_SLUG  # must have a slug
            ):
                classes.append(obj)
                log.debug(f"Found plugin class: {name} (slug={obj.ADDON_SLUG})")

    return classes


def list_all_addons() -> list:
    """Fetch all installed addons from Supervisor API for diagnostics."""
    try:
        r = httpx.get(
            f"{SUPERVISOR_URL}/addons",
            headers=_headers(),
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("data", {}).get("addons", [])
        log.warning(f"Supervisor /addons returned HTTP {r.status_code}")
        return []
    except Exception as e:
        log.error(f"Could not fetch addon list from Supervisor: {e}")
        return []


def discover_and_load_plugins(addon_options: dict) -> Dict[str, tuple]:
    """
    Main entry point: discover all plugin classes, check which addons
    are running, build PluginConfig for each, and return active plugins.

    Returns:
        Dict[plugin_name → (plugin_instance, PluginConfig)]
    """
    # Diagnostic: verify token and log all installed addon slugs
    token = _supervisor_token()
    log.info(f"Supervisor token: {'OK (' + str(len(token)) + ' chars)' if token else 'MISSING — addon discovery will not work'}")

    all_addons = list_all_addons()
    if all_addons:
        slugs = [a.get("slug") for a in all_addons]
        log.info(f"Supervisor reports {len(slugs)} installed addon(s): {', '.join(sorted(slugs))}")
    else:
        log.warning("Could not retrieve addon list from Supervisor — discovery may fail")

    plugin_classes = load_all_plugins()
    active = {}

    for cls in plugin_classes:
        log.info(f"Checking plugin {cls.NAME} (addon={cls.ADDON_SLUG})...")

        url = discover_addon_url(cls.ADDON_SLUG, cls.INTERNAL_PORT)
        if not url:
            log.info(f"  → {cls.NAME}: addon not found or not running, skipping")
            continue

        token = addon_options.get(cls.CONFIG_KEY, "") if cls.CONFIG_KEY else ""

        cfg = PluginConfig(
            url=url,
            token=token,
            extra={k: v for k, v in addon_options.items()},
        )

        instance = cls()
        active[cls.NAME] = (instance, cfg)
        log.info(f"  → {cls.NAME}: ACTIVE at {url}")

    return active
