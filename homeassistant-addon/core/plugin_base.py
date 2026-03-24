"""
BasePlugin — base class for all ha-mcp-plus plugins.

To add a new integration, create a file in plugins/ that:
1. Subclasses BasePlugin
2. Sets ADDON_SLUG, DEFAULT_PORT, NAME, DESCRIPTION
3. Implements register_tools(mcp, url, config)

The plugin is automatically discovered and loaded at startup
if the corresponding addon is installed and running.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import logging

log = logging.getLogger("ha-mcp-plus")


@dataclass
class PluginConfig:
    """Runtime config passed to each plugin after discovery."""
    url: str           # Auto-discovered URL (hostname:port from Supervisor)
    token: str         # Optional token from addon config
    extra: dict        # Any extra config fields


class BasePlugin(ABC):
    """
    Base class for all ha-mcp-plus plugins.

    Class attributes to set in subclass:
        NAME         : str  — friendly name (e.g. "InfluxDB")
        DESCRIPTION  : str  — one-liner for log output
        ADDON_SLUG   : str  — HA addon slug (e.g. "a0d7b954_influxdb")
        INTERNAL_PORT: int  — port inside the addon container
        CONFIG_KEY   : str  — key in addon options for the token (e.g. "influx_token")
    """

    NAME          : str = ""
    DESCRIPTION   : str = ""
    ADDON_SLUG    : str = ""
    INTERNAL_PORT : int = 0
    CONFIG_KEY    : str = ""   # token config key, empty = no token needed

    @classmethod
    def build_url(cls, hostname: str, port: int) -> str:
        return f"http://{hostname}:{port}"

    @classmethod
    def get_url_override(cls, addon_info: dict) -> Optional[str]:
        """
        Optional: return a direct URL based on addon_info, overriding the auto-discovered URL.
        Useful for proxy addons where the real backend URL is stored in addon options.
        Return None to use the auto-discovered URL.
        """
        return None

    @abstractmethod
    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        """Register all MCP tools for this plugin."""
        ...

    def __repr__(self):
        return f"<Plugin:{self.NAME}>"
