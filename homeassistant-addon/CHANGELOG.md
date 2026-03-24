## 0.7.12
- Fix: `esphome_list_devices` sloot `secrets.yaml` niet uit — nu gefilterd

## 0.7.11
- Fix: `esphome_list_devices` leest nu configs uit `/config/esphome/*.yaml` i.p.v. HTTP API — ESPHome redirect `/devices` altijd naar `/login` (checkt poort, niet header)

## 0.7.10
- Fix: ESPHome plugin stuurde `Authorization: Bearer SUPERVISOR_TOKEN` maar ESPHome gebruikt eigen auth — vervangen door `X-HA-Ingress: true` header (bleek niet voldoende)

## 0.7.9
- Refactor: `grafana_add_panel` vereenvoudigd — geen auto-build meer, query verplicht meegeven
- Gebruik `influxdb_find_entity` om de juiste query te krijgen, geef die door als `query` parameter
- Parameters verwijderd: `entity_ids`, `aggregation`, `window`, `range_hours`, `flux_query`, `influxql_query`
- Parameters toegevoegd: `query` (verplicht), `query_type` ('influxql' of 'flux')

## 0.7.8
- Fix: `grafana_add_panel` InfluxQL auto-build gebruikt nu `FROM /.*/` — HA v1 slaat data op in measurement genaamd naar de eenheid (`"W"`, `"kWh"`, `"°C"` etc.), niet in `"state"`

## 0.7.7
- Fix: `grafana_add_panel` auto-build InfluxQL query gebruikte `FROM /.*/` maar zette het terug naar `FROM "state"` — verkeerde aanname (state measurement bevat alleen on/off switches)

## 0.7.6
- Fix: `grafana_add_panel` gebruikte altijd Flux (`queryType: "flux"`) ook bij InfluxDB v1 — panelen bleven leeg
- Fix: datasource versie wordt nu automatisch gedetecteerd via Grafana API (`jsonData.version == "Flux"` → v2, anders v1)
- InfluxDB v1: query gebruikt nu `rawQuery: true` + InfluxQL met `$timeFilter` en `$__interval` (geen `queryType`)
- InfluxDB v2: bestaand Flux formaat behouden
- Nieuw parameter `influxql_query` voor expliciete InfluxQL override
- Datasource UID wordt nu meegegeven in panel target voor betere Grafana compatibiliteit

## 0.7.5
- Fix: `influxdb_find_entity` zocht met volledig entity_id incl. domein (`sensor.x`) maar HA slaat in InfluxDB alleen het object_id op (`x`) — domein wordt nu automatisch gestript
- Fix: zoektijdvenster uitgebreid van 1h naar 24h

## 0.7.4
- Herschreven: Z2M plugin gefocust op afgesproken scope
- Verwijderd: `z2m_device_set`, `z2m_device_get`, `z2m_get_device`, `z2m_list_devices`, `z2m_group_set`, `z2m_list_groups`, `z2m_bridge_config` (gebruik HA tools voor device control)
- Toegevoegd: `z2m_interview_device` — herinterviewen van een slecht herkend device
- Toegevoegd: `z2m_health_check` + `z2m_coordinator_check` — bridge en coordinator diagnostiek
- Toegevoegd: `z2m_network_map` — Zigbee netwerktopologie scan (resultaat in Z2M frontend)
- Toegevoegd: `z2m_lqi_overview` — signaalsterkte per device via HA linkquality entities
- Toegevoegd: `z2m_ota_check` + `z2m_ota_update` — firmware updates via OTA
- Toegevoegd: `z2m_bind` + `z2m_unbind` — directe Zigbee bindings tussen devices

## 0.7.3
- Fix: `z2m_device_set` en `z2m_group_set` — payload werd als JSON string doorgegeven door MCP, nu geparsed via `_parse_payload()`

## 0.7.2
- Fix: Z2M health/bridge_info gebruikten verkeerde entity namen — gecorrigeerd naar `binary_sensor.zigbee2mqtt_bridge_connection_state` etc. (gevonden via ha_search_entities)
- Fix: `z2m_permit_join` gebruikt nu `switch.zigbee2mqtt_bridge_permit_join` HA entity (eenvoudiger dan MQTT), MQTT als fallback voor specifieke router/duration
- `z2m_bridge_info` toont nu connection, version, permit_join en log_level

## 0.7.1
- Fix: Z2M plugin gebruikte verkeerde HA base URL (`http://supervisor/core/api` → `http://homeassistant:8123/api`)
- Fix: token-volgorde aangepast — `HA_REST_TOKEN` eerst (zelfde als HA plugin)

## 0.7.0
- Herschreven: Zigbee2MQTT plugin gebruikt nu MQTT via HA (`mqtt.publish` service) i.p.v. HTTP REST
- Z2M heeft geen REST API — alle commando's gaan via MQTT topics (`zigbee2mqtt/...`)
- Lezen gaat via HA entity states (bridge state, version, device states)
- Nieuw: `z2m_permit_join` — pairing aan/uitzetten met optionele router en tijdsduur
- Nieuw: `z2m_rename_device` — apparaat hernoemen via bridge request
- `z2m_device_set` en `z2m_group_set` gebruiken nu MQTT publish
- `z2m_health` en `z2m_bridge_info` lezen via `sensor.zigbee2mqtt_bridge_state` HA entity

## 0.6.8
- Fix: Zigbee2MQTT plugin gebruikte poort 8080 maar Z2M HA addon luistert op 8099 (frontend port) — connectie werkte nooit

## 0.6.7
- Fix: Supervisor API vereist `X-Supervisor-Token` header, niet `Authorization: Bearer` — dit was de echte oorzaak van alle auth-fouten
- Verwijderd: HA REST proxy fallback (`/api/hassio/`) — die route is geblacklist voor addons
- discovery.py en supervisor.py gebruiken nu allebei de juiste header

## 0.6.6
- Fix: Supervisor API fallback via HA REST proxy (`/api/hassio/...`) wanneer geen SUPERVISOR_TOKEN beschikbaar is
- Gebruikt `ha_token` uit config als long-lived token voor de proxy
- `supervisor_health` toont nu welke methode gebruikt wordt (direct vs proxy)
- discovery.py: zelfde proxy-fallback voor addon discovery bij opstarten

## 0.6.5
- Fix: Supervisor token ook ophalen uit `/proc/1/environ` als fallback (s6 init heeft token maar geeft hem niet altijd door aan child processes)
- `supervisor_health` toont nu ook of token via `/proc/1` gevonden werd

## 0.6.4
- Fix: Supervisor tools proberen nu ook `HASSIO_TOKEN` als `SUPERVISOR_TOKEN` leeg is (compatibiliteit oudere HA versies)
- Nieuw: `supervisor_health` tool — toont token-beschikbaarheid en Supervisor API bereikbaarheid voor diagnose
- Log waarschuwing als geen token gevonden in omgeving

## 0.6.3
- Fix: SupervisorPlugin werd nooit geladen — expliciete registratie toegevoegd in server.py (net als filesystem/homeassistant plugins)
- Fix: SupervisorPlugin gebruikte `ha_token` uit config i.p.v. `SUPERVISOR_TOKEN` env var (juiste auth voor Supervisor API)

## 0.6.2
- Fix: InfluxDB v1 authenticatie — `influx_username` en `influx_password` toegevoegd aan config
- InfluxDB v1 stuurt credentials als `?u=&p=` query params als geconfigureerd

## 0.6.1
- Fix: "Session not found" na addon herstart of inactiviteit
- MCP server draait nu in stateless mode — geen server-side sessies, elke tool call is onafhankelijk
- Fallback naar stateful mode als de FastMCP versie stateless_http niet ondersteunt

## 0.6.0
- InfluxDB: auto-detectie van v1 (InfluxQL) vs v2 (Flux) via `/health` endpoint
- InfluxDB v1: queries via `/query` met InfluxQL syntax
- InfluxDB v2: queries via `/api/v2/query` met Flux syntax
- `influxdb_build_grafana_query` geeft nu beide query-varianten terug + detected_version

## 0.6.0-pre (was 0.5.30)
- ESPHome: `esphome_read_config` — lees bestaande YAML config
- ESPHome: `esphome_write_config` — schrijf/maak nieuwe YAML config voor een device
- ESPHome: `esphome_compile` — compileer firmware via ESPHome API
- ESPHome: `esphome_upload` — OTA flash naar een online device

## 0.5.29
- Verwijderd: IP filter middleware — Docker NAT maakt het onmogelijk om het echte client-IP te zien; alle verbindingen kwamen binnen als 172.30.32.1
- Beveiliging rust nu volledig op het geheime pad (`mcp_secret_path`)
- Verwijderd: `allowed_networks` config optie

## 0.5.28
- Fix: Docker bridge host gateway (172.30.32.1) werd geblokkeerd — HA Supervisor gebruikt 172.30.32.0/23, addon zit op 172.30.33.x waardoor de gateway buiten het /24 viel
- IP-detectie gebruikt nu /16 voor 172.16.0.0/12 (Docker-range) in plaats van /24 — dekt zowel addon-containers als host gateway

## 0.5.27
- Fix: Docker bridge netwerk (172.30.x.x) en HA host LAN worden nu altijd automatisch gedetecteerd en toegestaan
- `allowed_networks` is nu additief — overschrijft nooit de auto-detectie, alleen extra netwerken erbij
- Loopback altijd toegestaan

## 0.5.26
- Fix: FastMCP import volgorde gewijzigd — importeer nu eerst `fastmcp.FastMCP` (heeft `http_app`), dan pas `mcp.server.fastmcp.FastMCP`, dan `mcp.server.mcpserver.MCPServer`
- Dit was de oorzaak van de `AttributeError: 'FastMCP' object has no attribute 'http_app'` crash

## 0.5.25
- Gegenereerd pad wordt primair geschreven naar `/config/ha_mcp_plus_path.txt`
- Zichtbaar via Bestandsbeheerder of Studio Code Server in HA (gegarandeerd via config:rw)

## 0.5.24
- Fix: sensor state schrijven gebruikte PUT i.p.v. POST (HA REST API vereist POST voor /api/states/)

## 0.5.23
- Gegenereerd pad wordt gepubliceerd als `sensor.ha_mcp_plus_endpoint` (Developer Tools → States)
- Én als persistente notificatie (bel-icoon in HA UI)

## 0.5.22
- Gegenereerd pad wordt nu ook geschreven naar HA Systeem Logboek (Instellingen → Systeem → Logboek)
- Zichtbaar als waarschuwing van `ha_mcp_plus` — ook als Configuration tab niet ververst

## 0.5.21
- Fix: `/mcp` (oude default) wordt nu ook behandeld als leeg — pad wordt automatisch gegenereerd i.p.v. foutmelding

## 0.5.20
- Security: `mcp_secret_path` leeg laten genereert automatisch een uniek pad bij eerste start
- Na generatie wordt het pad opgeslagen in de Configuration tab via Supervisor API, daarna stopt de addon — herstart vereist
- Bij herstart is het pad ingesteld en de addon draait normaal
- Verwijderd: auto-generatie via `/data/generated_mcp_path.txt` en HA notificatie (te onbetrouwbaar)
- `mcp_secret_path: /mcp` is nu expliciet verboden (geeft foutmelding bij opstarten)

## 0.5.19
- Security: gegenereerd MCP pad wordt teruggeschreven naar addon options — zichtbaar in de Configuration tab op de addon info pagina

## 0.5.18
- Security: actief MCP pad zichtbaar als persistente HA notificatie (bel-icoon in HA UI) bij elke start

## 0.5.17
- Security: IP filtering middleware — alleen verbindingen vanuit toegestane subnets worden geaccepteerd (auto-detect lokaal subnet, uitbreidbaar via `allowed_networks`)
- Security: `sandbox_enabled` config optie — sandbox staat standaard UIT, expliciet aan te zetten
- Security: `mcp_secret_path` leeg laten genereert automatisch een random UUID-pad bij eerste start (persistent in /data)
- Dependency: uvicorn toegevoegd voor directe ASGI app controle

## 0.5.16
- Nieuw: Python Sandbox tool (`python_sandbox`) — altijd actief, voert willekeurige Python code uit server-side
- Pre-geconfigureerd met InfluxDB, numpy, pandas, requests en HA Supervisor toegang
- Iteratiebescherming via `attempt`/`max_attempts` parameters — stopt na max pogingen en vraagt om gebruikersinput

## 0.5.15
- Fix: Music Assistant plugin herschreven met WebSocket API (was HTTP REST, werkt niet)

## 0.5.14
- Nieuw: Music Assistant plugin met `ma_health`, `ma_list_players`, `ma_search`, `ma_get_queue`, `ma_player_command`
- Nieuw veld `ma_token` in addon config voor MA Bearer auth

## 0.5.13
- Fix: ESPHome requests sturen nu Supervisor token mee als Bearer auth

## 0.5.12
- Fix: ESPHome `list_devices` gebruikt nu correct `/devices` endpoint (was `/devices.json`)
- Fix: `get_device_logs` en `validate_config` geven nu duidelijke foutmelding (vereisen WebSocket, nog niet geïmplementeerd)

## 0.5.11
- Fix: ESPHome health check volgt nu redirects (`follow_redirects=True`) — was eerder kapot bij addons die `/` redirecten

## 0.5.10
- Nieuw tool: `nodered_update_flow` — update een bestaande Node-RED flow tab via PUT zonder de hele tab te verwijderen

## 0.5.9
- Nieuw tool: `ha_set_state` — zet de state van een entity direct in de HA state machine (handig voor testen van flows/automaties)

## 0.5.8
- Fix: Node-RED `nodered_list_flows` crashte op Node-RED v2 API response (`{"flows": [...]}` in plaats van een lijst)

## 0.5.7
- Addon discovery now uses name pattern matching instead of hardcoded full slugs
- Plugins match on the name part of the slug (e.g. `influxdb` matches `a0d7b954_influxdb` or any other prefix)
- Makes discovery resilient to different repository prefixes across installations
- Falls back to direct slug lookup if the addon list is unavailable

## 0.5.6
- Fix: Zigbee2MQTT addon slug corrected (`45df7312_zigbee2mqtt` instead of `a0d7b954_zigbee2mqtt`)

## 0.5.5
- Fix: Supervisor token poisoning introduced in v0.5.3
- `ha_token` is now injected as `HA_REST_TOKEN` instead of `HA_TOKEN` to prevent interfering with Supervisor token discovery
- Addon plugin discovery works correctly again

## 0.5.4
- Fix: Supervisor API returned 403 for all addon discovery calls
- Changed `hassio_role` from `manager` to `admin` — required for Supervisor `/addons` endpoint access

## 0.5.3
- New: `ha_token` config option (password field) for use outside HA (local dev, Claude Desktop)
- All token fields (`ha_token`, `influx_token`, `grafana_token`, `nodered_token`, `z2m_token`) are now masked as password in the HA UI
- When running as addon, Supervisor token is still used automatically — `ha_token` only activates when no Supervisor token is present

## 0.5.2
- New plugin: Zigbee2MQTT — list devices/groups, get device info, control devices via Z2M REST API
- Optional `z2m_token` config for installations with Z2M auth enabled

## 0.5.1
- New tools: `ha_list_statistic_ids` and `ha_get_statistics` for long-term energy/sensor statistics
- Added WebSocket helper for HA recorder API access

## 0.5.0
- HomeAssistant plugin expanded to full REST API coverage
- New tool categories: entity registry, device registry, area/floor/label registry, zones
- New tools: calendar, todo lists, scenes, groups, update entities, automation traces
- New tools: dashboards (Lovelace), helpers, scripts CRUD

## 0.4.0
- New plugin: HomeAssistant core tools (always active)
- Tools: entity states, service calls, events, history, logbook, automations, scripts, template rendering, system health

## 0.3.7
- Fix: Node-RED flow list skips non-dict items in `/flows` response

## 0.3.6
- Node-RED: removed auth complexity, assumes admin auth is disabled (default)
- Simplified Node-RED connection — no credentials needed in default setup

## 0.3.0 – 0.3.5
- Node-RED plugin added: list flows, get flow details, create/deploy flows
- Multiple fixes to Node-RED authentication and nginx proxy handling

## 0.2.9
- Robust Supervisor token discovery: checks environment variables, s6 container files, and `/proc/1/environ`

## 0.2.5 – 0.2.8
- Diagnostic logging improvements
- Fix: token propagation to Python process
- Fix: empty SUPERVISOR_TOKEN crash

## 0.2.0
- Modular plugin system with auto-discovery
- Plugins: ESPHome, Frigate, Grafana, InfluxDB, Node-RED
- Safety guard for destructive operations
- Automatic addon URL discovery via Supervisor API
