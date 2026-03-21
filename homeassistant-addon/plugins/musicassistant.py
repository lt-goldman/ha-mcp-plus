"""
Music Assistant plugin — auto-activated when music_assistant addon is running.

Uses the Music Assistant WebSocket API (port 8095).
"""

import json
import logging
import uuid
from typing import Any, Optional

import websocket
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.musicassistant")


class MusicAssistantPlugin(BasePlugin):
    NAME          = "Music Assistant"
    DESCRIPTION   = "Search and control Music Assistant — players, queues, library"
    ADDON_SLUG    = "music_assistant"
    INTERNAL_PORT = 8095
    CONFIG_KEY    = "ma_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        ws_url = cfg.url.replace("http://", "ws://") + "/ws"
        token  = cfg.token

        def _call(command: str, args: dict = None) -> Any:
            """Send a single command over WebSocket and return the result."""
            message_id = str(uuid.uuid4())
            msg = {"message_id": message_id, "command": command, "args": args or {}}
            headers = [f"Authorization: Bearer {token}"] if token else []

            ws = websocket.WebSocket()
            try:
                ws.connect(ws_url, header=headers, timeout=10)
                # MA sends a server_info message on connect — consume it
                ws.recv()
                ws.send(json.dumps(msg))
                while True:
                    raw = ws.recv()
                    resp = json.loads(raw)
                    if resp.get("message_id") == message_id:
                        if "error_code" in resp:
                            return {"error": resp.get("details", resp.get("error_code"))}
                        return resp.get("result")
            finally:
                ws.close()

        @mcp.tool()
        def ma_health() -> dict:
            """Check Music Assistant connectivity and version."""
            try:
                message_id = str(uuid.uuid4())
                headers = [f"Authorization: Bearer {token}"] if token else []
                ws = websocket.WebSocket()
                ws.connect(ws_url, header=headers, timeout=5)
                raw = ws.recv()  # server_info
                ws.close()
                info = json.loads(raw)
                return {
                    "connected": True,
                    "version": info.get("server_version"),
                    "schema": info.get("schema_version"),
                }
            except Exception as e:
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def ma_list_players() -> dict:
            """List all Music Assistant players and their current state."""
            try:
                players = _call("players/all")
                if isinstance(players, dict) and "error" in players:
                    return players
                return {
                    "count": len(players),
                    "players": [
                        {
                            "player_id": p.get("player_id"),
                            "name": p.get("display_name"),
                            "state": p.get("state"),
                            "volume": p.get("volume_level"),
                            "powered": p.get("powered"),
                        }
                        for p in (players or [])
                    ],
                }
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def ma_search(query: str, media_type: Optional[str] = None) -> dict:
            """
            Search the Music Assistant library.

            Args:
                query: Search term (artist, album, track, playlist).
                media_type: Optional filter: 'track', 'album', 'artist', 'playlist'.
            """
            try:
                args = {"search_query": query, "limit": 10}
                if media_type:
                    args["media_types"] = [media_type]
                result = _call("music/search", args)
                if isinstance(result, dict) and "error" in result:
                    return result
                return result or {}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def ma_get_queue(queue_id: str) -> dict:
            """
            Get the current playback queue for a player.

            Args:
                queue_id: Player/queue ID as returned by ma_list_players.
            """
            try:
                result = _call("player_queues/items", {"queue_id": queue_id, "limit": 20, "offset": 0})
                if isinstance(result, dict) and "error" in result:
                    return result
                return {"queue_id": queue_id, "items": result or []}
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def ma_player_command(player_id: str, command: str, value: Optional[str] = None) -> dict:
            """
            Send a command to a Music Assistant player.

            Args:
                player_id: Player ID as returned by ma_list_players.
                command: One of 'play', 'pause', 'stop', 'next', 'previous', 'volume_set', 'power'.
                value: Required for volume_set (0-100) or power ('true'/'false').
            """
            try:
                cmd_map = {
                    "play":     "player_queues/play",
                    "pause":    "player_queues/pause",
                    "stop":     "player_queues/stop",
                    "next":     "player_queues/next",
                    "previous": "player_queues/previous",
                    "volume_set": "players/cmd/volume_set",
                    "power":    "players/cmd/power",
                }
                ws_command = cmd_map.get(command)
                if not ws_command:
                    return {"error": f"Unknown command '{command}'. Valid: {list(cmd_map.keys())}"}

                args = {"queue_id" if command in ("play", "pause", "stop", "next", "previous") else "player_id": player_id}
                if value is not None:
                    args["volume_level" if command == "volume_set" else "powered"] = value
                result = _call(ws_command, args)
                if isinstance(result, dict) and "error" in result:
                    return result
                return {"success": True, "player_id": player_id, "command": command}
            except Exception as e:
                return {"error": str(e)}
