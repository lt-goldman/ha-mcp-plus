"""
HA WebSocket helper — one-shot request/response over the HA WebSocket API.

Usage:
    result = ha_ws_call(token, "ws://homeassistant:8123", {"type": "recorder/list_statistic_ids"})

Protocol:
    1. Connect to ws://{host}/api/websocket
    2. Receive auth_required
    3. Send auth with token
    4. Receive auth_ok
    5. Send command with id=1
    6. Receive result with id=1
    7. Close
"""

import json
import logging
import websocket

log = logging.getLogger("ha-mcp-plus.websocket")

_WS_TIMEOUT = 30


def ha_ws_call(token: str, base_url: str, command: dict) -> dict:
    """
    Send a single command over the HA WebSocket API and return the result.

    Args:
        token:    HA/Supervisor token.
        base_url: HA base URL, e.g. 'http://homeassistant:8123'.
        command:  Dict with 'type' and any other required fields.
                  Do NOT include 'id' — it is added automatically.

    Returns:
        The 'result' field from the HA response, or a dict with 'error'.
    """
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
    ws = websocket.WebSocket()

    try:
        ws.connect(ws_url, timeout=_WS_TIMEOUT)

        # 1. Receive auth_required
        msg = json.loads(ws.recv())
        if msg.get("type") != "auth_required":
            return {"error": f"Expected auth_required, got: {msg.get('type')}"}

        # 2. Authenticate
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        msg = json.loads(ws.recv())
        if msg.get("type") != "auth_ok":
            return {"error": f"Authentication failed: {msg.get('message', msg.get('type'))}"}

        # 3. Send command
        cmd = {"id": 1, **command}
        ws.send(json.dumps(cmd))

        # 4. Wait for result matching our id
        while True:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == 1:
                break
            # ignore other messages (e.g. state change events)

        if not msg.get("success", False):
            error = msg.get("error", {})
            return {"error": error.get("message", "Unknown error"), "code": error.get("code")}

        return msg.get("result")

    except websocket.WebSocketTimeoutException:
        return {"error": f"WebSocket timeout connecting to {ws_url}"}
    except ConnectionRefusedError:
        return {"error": f"Cannot connect to HA WebSocket at {ws_url}"}
    except Exception as e:
        log.error(f"[WebSocket] Unexpected error: {e}")
        return {"error": str(e)}
    finally:
        try:
            ws.close()
        except Exception:
            pass
