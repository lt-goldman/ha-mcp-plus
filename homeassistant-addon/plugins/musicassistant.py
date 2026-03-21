"""
Music Assistant plugin — auto-activated when music_assistant addon is running.
"""

import httpx
import logging
from typing import Optional
from core.plugin_base import BasePlugin, PluginConfig

log = logging.getLogger("ha-mcp-plus.musicassistant")


class MusicAssistantPlugin(BasePlugin):
    NAME          = "Music Assistant"
    DESCRIPTION   = "Search and control Music Assistant — players, queues, library"
    ADDON_SLUG    = "music_assistant"
    INTERNAL_PORT = 8095
    CONFIG_KEY    = "ma_token"

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        url = cfg.url
        token = cfg.token

        def _headers() -> dict:
            if token:
                return {"Authorization": f"Bearer {token}"}
            return {}

        @mcp.tool()
        def ma_health() -> dict:
            """Check Music Assistant connectivity."""
            try:
                r = httpx.get(f"{url}/", timeout=5, follow_redirects=True, headers=_headers())
                if not r.is_success:
                    log.error(f"[MA] Health check failed: HTTP {r.status_code}")
                    return {"connected": False, "error": f"HTTP {r.status_code}"}
                log.debug(f"[MA] Health check OK at {url}")
                return {"connected": True}
            except httpx.ConnectError:
                return {"connected": False, "error": f"Cannot connect to Music Assistant at {url}"}
            except Exception as e:
                return {"connected": False, "error": str(e)}

        @mcp.tool()
        def ma_list_players() -> dict:
            """List all Music Assistant players and their current state."""
            try:
                r = httpx.get(f"{url}/api/players", timeout=10, headers=_headers())
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}"}
                players = r.json()
                return {
                    "count": len(players),
                    "players": [
                        {
                            "player_id": p.get("player_id"),
                            "name": p.get("display_name"),
                            "state": p.get("state"),
                            "volume": p.get("volume_level"),
                            "powered": p.get("powered"),
                            "current_item": p.get("current_media", {}).get("name") if p.get("current_media") else None,
                        }
                        for p in (players if isinstance(players, list) else players.get("items", []))
                    ],
                }
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def ma_search(query: str, media_type: str = "all") -> dict:
            """
            Search the Music Assistant library.

            Args:
                query: Search term (artist, album, track, playlist).
                media_type: One of 'all', 'track', 'album', 'artist', 'playlist'. Default: 'all'.
            """
            try:
                params = {"query": query}
                if media_type != "all":
                    params["media_type"] = media_type
                r = httpx.get(f"{url}/api/search", params=params, timeout=10, headers=_headers())
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}"}
                return r.json()
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def ma_get_queue(player_id: str) -> dict:
            """
            Get the current playback queue for a player.

            Args:
                player_id: Player ID as returned by ma_list_players.
            """
            try:
                r = httpx.get(f"{url}/api/player_queues/{player_id}/items", timeout=10, headers=_headers())
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}"}
                return r.json()
            except Exception as e:
                return {"error": str(e)}

        @mcp.tool()
        def ma_player_command(player_id: str, command: str, value: Optional[str] = None) -> dict:
            """
            Send a command to a Music Assistant player.

            Args:
                player_id: Player ID as returned by ma_list_players.
                command: One of 'play', 'pause', 'stop', 'next', 'previous', 'volume_set'.
                value: Required for volume_set (0-100).
            """
            try:
                payload = {"command": command}
                if value is not None:
                    payload["value"] = value
                r = httpx.post(
                    f"{url}/api/players/{player_id}/command",
                    json=payload,
                    timeout=10,
                    headers=_headers(),
                )
                if not r.is_success:
                    return {"error": f"HTTP {r.status_code}"}
                return {"success": True, "player_id": player_id, "command": command}
            except Exception as e:
                return {"error": str(e)}
