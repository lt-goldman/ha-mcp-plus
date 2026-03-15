name: "HA MCP Plus"
description: "Extended MCP server — Filesystem, InfluxDB, Grafana, Node-RED, Frigate & Supervisor control for AI assistants"
version: "0.1.0"
slug: "ha_mcp_plus"
init: false
homeassistant_api: true
hassio_api: true
hassio_role: manager
auth_api: true
map:
  - config:rw

ports:
  9583/tcp: 9583

ports_description:
  9583/tcp: "MCP Server (HTTP/SSE)"

schema:
  mcp_secret_path: str
  influx_url: str
  influx_token: str
  influx_org: str
  influx_bucket: str
  grafana_url: str
  grafana_token: str
  nodered_url: str
  nodered_token: str
  frigate_url: str
  log_level: list(trace|debug|info|notice|warning|error|fatal)?

options:
  mcp_secret_path: "/mcp"
  influx_url: "http://a0d7b954-influxdb:8086"
  influx_token: ""
  influx_org: "homeassistant"
  influx_bucket: "homeassistant"
  grafana_url: "http://a0d7b954-grafana:3000"
  grafana_token: ""
  nodered_url: "http://a0d7b954-nodered:1880"
  nodered_token: ""
  frigate_url: "http://ccab4aaf-frigate:5000"
  log_level: "info"
