"""
Python Sandbox plugin — always active.

Executes arbitrary Python code server-side with access to InfluxDB,
numpy, pandas, and the HA Supervisor API. Returns stdout/stderr/exceptions.

Iteration guard: attempt/max_attempts prevents endless AI retry loops.
"""

import os
import sys
import subprocess
import tempfile
import textwrap
import logging

from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.sandbox")

_PREAMBLE = """\
import os, sys, json, math, statistics
import requests

try:
    import numpy as np
except ImportError:
    pass

try:
    import pandas as pd
except ImportError:
    pass

# InfluxDB — pre-configured from MCP options
INFLUX_URL    = {influx_url!r}
INFLUX_TOKEN  = {influx_token!r}
INFLUX_ORG    = {influx_org!r}
INFLUX_BUCKET = {influx_bucket!r}

try:
    from influxdb_client import InfluxDBClient
    if INFLUX_TOKEN:
        _client   = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        query_api = _client.query_api()
except ImportError:
    pass

# HA access
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_HEADERS = {{
    "Authorization": f"Bearer {{SUPERVISOR_TOKEN}}",
    "Content-Type": "application/json",
}}

"""


class SandboxPlugin(BasePlugin):
    NAME          = "Sandbox"
    DESCRIPTION   = "Execute Python code server-side with InfluxDB and HA access"
    ADDON_SLUG    = ""   # always active — registered directly in server.py
    INTERNAL_PORT = 0
    CONFIG_KEY    = ""

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        influx_url    = cfg.extra.get("_influx_url", "")
        influx_token  = cfg.extra.get("influx_token", "")
        influx_org    = cfg.extra.get("influx_org", "homeassistant")
        influx_bucket = cfg.extra.get("influx_bucket", "homeassistant")

        preamble = _PREAMBLE.format(
            influx_url=influx_url,
            influx_token=influx_token,
            influx_org=influx_org,
            influx_bucket=influx_bucket,
        )

        @mcp.tool()
        def python_sandbox(
            code: str,
            attempt: int = 1,
            max_attempts: int = 5,
            timeout: int = 60,
        ) -> dict:
            """
            Execute Python code server-side. Returns stdout, stderr, and exceptions.

            Pre-configured globals: numpy (np), pandas (pd), requests,
            influxdb_client (query_api), INFLUX_BUCKET, HA_HEADERS.

            Args:
                code:         Python code to execute.
                attempt:      Current attempt number — increment on each retry.
                max_attempts: Hard stop when exceeded — ask user for help (default 5).
                timeout:      Max execution time in seconds (default 60).
            """
            if attempt > max_attempts:
                return {
                    "error": "max_attempts_reached",
                    "message": (
                        f"Reached {max_attempts} attempts without success. "
                        "Stop retrying and ask the user for guidance."
                    ),
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                }

            full_code = preamble + "# --- user code ---\n" + textwrap.dedent(code)

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as f:
                    f.write(full_code)
                    tmp_path = f.name

                result = subprocess.run(
                    [sys.executable, tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={**os.environ},
                )
                return {
                    "success":      result.returncode == 0,
                    "returncode":   result.returncode,
                    "stdout":       result.stdout[:8000],
                    "stderr":       result.stderr[:3000],
                    "attempt":      attempt,
                    "max_attempts": max_attempts,
                }

            except subprocess.TimeoutExpired:
                log.error(f"[Sandbox] Timeout after {timeout}s")
                return {
                    "error":   "timeout",
                    "message": f"Execution exceeded {timeout}s. Reduce data range or simplify the code.",
                    "attempt": attempt,
                }
            except Exception as e:
                log.error(f"[Sandbox] Unexpected error: {e}")
                return {"error": str(e), "attempt": attempt}
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
