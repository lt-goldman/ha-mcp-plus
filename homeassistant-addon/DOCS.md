# HA MCP Plus — Documentation

## Setup

1. Install the addon from the store
2. Configure tokens (only for addons that require auth):
   - **InfluxDB token**: Only if InfluxDB auth is enabled
   - **Grafana token**: Only if Grafana is not in anonymous mode  
   - **Node-RED token**: Only if Node-RED has auth enabled
3. Start the addon
4. Add to Claude.ai as a remote MCP connector:
   ```
   https://your-ha-url:9584/mcp
   ```

## How autodiscovery works

On startup, ha-mcp-plus queries the Supervisor API to find which addons
are installed and running. For each detected addon, it:
- Resolves the correct internal hostname and port
- Activates the corresponding plugin tools
- Logs which plugins are active

You will see something like this in the addon logs:
```
Discovered a0d7b954-influxdb → http://a0d7b954-influxdb:8086
  → InfluxDB: ACTIVE
Discovered a0d7b954-grafana → http://a0d7b954-grafana:3000
  → Grafana: ACTIVE
  → Node-RED: addon not found or not running, skipping
```

## Adding a new plugin

Create a file in `src/plugins/your_addon.py`:

```python
from core.plugin_base import BasePlugin, PluginConfig

class MyAddonPlugin(BasePlugin):
    NAME          = "My Addon"
    DESCRIPTION   = "What this plugin does"
    ADDON_SLUG    = "repository_slug_myaddon"  # from HA addon store
    INTERNAL_PORT = 8080
    CONFIG_KEY    = "myaddon_token"  # key in addon options, empty if no auth

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url     # auto-discovered
        token = cfg.token # from config

        @mcp.tool()
        def myaddon_do_something() -> dict:
            """Tool description here."""
            ...
```

That's it — the plugin is automatically discovered and loaded at startup
if the corresponding addon is running.

## Supported addons

| Addon | Slug | Port | Token needed? |
|-------|------|------|---------------|
| InfluxDB | a0d7b954_influxdb | 8086 | Yes (if auth enabled) |
| Grafana | a0d7b954_grafana | 3000 | Yes (if not anonymous) |
| Node-RED | a0d7b954_nodered | 1880 | Yes (if auth enabled) |
| Frigate | ccab4aaf_frigate-proxy | 5000 | No |
| ESPHome | 5c53de3b_esphome | 6052 | No (uses HA auth) |
| Filesystem | — | — | Always active |
