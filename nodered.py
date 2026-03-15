#!/usr/bin/with-contenv bashio

bashio::log.info "Starting HA MCP Plus..."

export HA_URL="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export CONFIG_PATH="/config"
export MCP_PORT="9583"
export MCP_SECRET_PATH="$(bashio::config 'mcp_secret_path')"
export INFLUX_URL="$(bashio::config 'influx_url')"
export INFLUX_TOKEN="$(bashio::config 'influx_token')"
export INFLUX_ORG="$(bashio::config 'influx_org')"
export INFLUX_BUCKET="$(bashio::config 'influx_bucket')"
export GRAFANA_URL="$(bashio::config 'grafana_url')"
export GRAFANA_TOKEN="$(bashio::config 'grafana_token')"
export NODERED_URL="$(bashio::config 'nodered_url')"
export NODERED_TOKEN="$(bashio::config 'nodered_token')"
export FRIGATE_URL="$(bashio::config 'frigate_url')"

cd /app
exec python -u server.py
