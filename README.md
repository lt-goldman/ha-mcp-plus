# ha-mcp-plus

**Extended Home Assistant MCP Server**

Adds powerful new tools on top of the excellent [ha-mcp](https://github.com/homeassistant-ai/ha-mcp) by [@homeassistant-ai](https://github.com/homeassistant-ai), giving AI assistants (Claude, etc.) full control over your smart home stack.

---

## 🙏 Credits & Thanks

This project builds directly on the work of **Julien** and the contributors of [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp) — the unofficial and awesome Home Assistant MCP Server.

Without their foundation (80+ tools, addon structure, Supervisor integration) this project would not exist. If you find ha-mcp-plus useful, please also ⭐ star their repo!

- **ha-mcp GitHub:** https://github.com/homeassistant-ai/ha-mcp
- **License:** MIT (same as ha-mcp)

---

## What's included

ha-mcp-plus extends ha-mcp with tools for services that ha-mcp doesn't cover:

| Module | Tools | Description |
|--------|-------|-------------|
| **Filesystem** | `filesystem_read_config`, `filesystem_append_config`, `filesystem_write_file`, `filesystem_list_files` | Read/write configuration.yaml and /config files — with full safety guard |
| **InfluxDB** | `influxdb_health`, `influxdb_list_measurements`, `influxdb_find_entity`, `influxdb_query`, `influxdb_build_grafana_query` | Query InfluxDB, find entity measurements, build Grafana-ready Flux queries |
| **Grafana** | `grafana_health`, `grafana_list_dashboards`, `grafana_get_dashboard`, `grafana_create_dashboard`, `grafana_add_panel`, `grafana_get_datasources` | Create dashboards and panels via the Grafana API with auto-generated InfluxDB queries |
| **Node-RED** | `nodered_health`, `nodered_list_flows`, `nodered_get_flow`, `nodered_deploy_flow_safe`, `nodered_delete_flow`, `nodered_build_ha_trigger_flow` | Read, create and deploy Node-RED flows — with safety guard |
| **Frigate** | `frigate_health`, `frigate_get_cameras`, `frigate_get_events`, `frigate_get_stats`, `frigate_get_event_counts`, `frigate_get_recordings`, `frigate_get_labels` | Access Frigate camera events, recordings and stats |
| **ESPHome** | `esphome_health`, `esphome_list_devices`, `esphome_get_device_logs`, `esphome_validate_config` | Manage ESPHome devices |
| **Supervisor** | `supervisor_list_addons`, `supervisor_addon_info`, `supervisor_addon_start/stop/restart`, `supervisor_addon_logs`, `supervisor_check_config`, `supervisor_restart_ha`, `supervisor_reload_core`, `supervisor_system_info` | Control HA add-ons — dangerous ops require explicit execute=True |

---

## 🔒 Safety Guard

All high-risk operations (writing files, deploying flows, restarting HA) show a full safety analysis **before** doing anything:

- ✅ What exactly will happen
- ✅ Which resources are affected
- ✅ Risk percentage (chance system stops working)
- ✅ Recovery time estimate
- ✅ Rollback instructions
- ✅ Alternatives

Nothing is executed until you explicitly say so. You can discuss and improve the plan first.

---

## 🔍 Autodiscovery

On startup, ha-mcp-plus queries the Supervisor API to find which addons are installed and running. For each detected addon it:

- Resolves the correct internal hostname and port (even if non-default)
- Activates the corresponding plugin tools
- Skips plugins for addons that aren't running

**Configuration is minimal** — only tokens need to be filled in. URLs are fully automatic.

---

## Installation

### As a Home Assistant Add-on

1. Add this repository to your HA add-on store:
   ```
   Settings → Add-ons → Add-on Store → ⋮ → Repositories
   Add: https://github.com/lt-goldman/ha-mcp-plus
   ```

2. Install **HA MCP Plus** from the store.

3. Configure tokens (only for addons that require authentication).

4. Start the add-on — it exposes a MCP server on port 9584.

5. Add to Claude.ai as a remote MCP connector:
   ```
   https://your-ha-url:9584/mcp
   ```

---

## Adding a new plugin

Create a file in `src/plugins/your_addon.py`:

```python
from core.plugin_base import BasePlugin, PluginConfig

class MyAddonPlugin(BasePlugin):
    NAME          = "My Addon"
    DESCRIPTION   = "What this plugin does"
    ADDON_SLUG    = "repository_slug_myaddon"
    INTERNAL_PORT = 8080
    CONFIG_KEY    = "myaddon_token"  # empty if no auth needed

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url     # auto-discovered
        token = cfg.token # from config

        @mcp.tool()
        def myaddon_do_something() -> dict:
            """Tool description."""
            ...
```

That's it — the plugin is automatically discovered and loaded.

---

## License

MIT — built on top of [ha-mcp](https://github.com/homeassistant-ai/ha-mcp) (also MIT).
