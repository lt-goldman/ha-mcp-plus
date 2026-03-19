"""
Filesystem plugin — read/write HA config files.
All write operations go through SafetyGuard: full plan + risk analysis shown
BEFORE execution. Nothing is written unless execute=True is explicitly set.
"""

import os
import logging
import shutil
import yaml
from datetime import datetime
from typing import Optional
from core.plugin_base import BasePlugin, PluginConfig
from core.safety import plan_append_config_yaml, plan_write_file

log = logging.getLogger("ha-mcp-plus.filesystem")


class FilesystemPlugin(BasePlugin):
    NAME          = "Filesystem"
    DESCRIPTION   = "Read/write configuration.yaml and files in /config (with safety guard)"
    ADDON_SLUG    = ""
    INTERNAL_PORT = 0
    CONFIG_KEY    = ""

    def register_tools(self, mcp, cfg: PluginConfig) -> None:
        config_path = cfg.extra.get("config_path", "/config")

        @mcp.tool()
        def filesystem_read_config(section: Optional[str] = None) -> dict:
            """
            Read configuration.yaml or a specific top-level section.

            Args:
                section: Top-level key to return (e.g. 'template', 'sensor').
                         If None, returns full file as text.
            """
            path = os.path.join(config_path, "configuration.yaml")
            if not os.path.exists(path):
                log.error(f"[Filesystem] configuration.yaml not found at {path}")
                return {"error": f"Not found: {path}"}
            with open(path) as f:
                content = f.read()
            log.debug(f"[Filesystem] Read configuration.yaml ({len(content.splitlines())} lines)")
            if section is None:
                return {"content": content, "lines": len(content.splitlines())}
            try:
                data = yaml.safe_load(content) or {}
                return {"section": section, "content": data.get(section), "exists": section in data}
            except yaml.YAMLError as e:
                log.error(f"[Filesystem] YAML parse error in configuration.yaml: {e}")
                return {"error": str(e)}

        @mcp.tool()
        def filesystem_list_files(subdir: str = "") -> dict:
            """List files in /config or a subdirectory."""
            base = os.path.join(config_path, subdir.lstrip("/"))
            if not os.path.exists(base):
                return {"error": f"Not found: {base}"}
            files = []
            for root, dirs, filenames in os.walk(base):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                rel = os.path.relpath(root, config_path)
                for f in filenames:
                    files.append(os.path.join(rel, f))
            return {"base": base, "files": sorted(files)[:200]}

        @mcp.tool()
        def filesystem_append_config(
            yaml_block: str,
            comment: str = "",
            execute: bool = False,
        ) -> dict:
            """
            Append a YAML block to configuration.yaml.

            HIGH RISK — shows full safety analysis before doing anything.
            Set execute=True only after reviewing and agreeing with the plan.

            Args:
                yaml_block: Valid YAML to append.
                comment: Description of what is being added.
                execute: False (default) = show plan only. True = actually write.
            """
            plan = plan_append_config_yaml(yaml_block, comment, config_path)

            if not execute:
                return {
                    "status": "PLAN_READY",
                    "message": "Nog niets uitgevoerd. Bekijk het plan hieronder en reageer.",
                    "plan": plan.render(),
                    "next_step": "Roep deze tool opnieuw aan met execute=True als je akkoord gaat, of stel vragen/verbeteringen voor.",
                }

            try:
                yaml.safe_load(yaml_block)
            except yaml.YAMLError as e:
                log.error(f"[Filesystem] Invalid YAML block rejected: {e}")
                return {"success": False, "error": f"Ongeldige YAML: {e}"}

            path = os.path.join(config_path, "configuration.yaml")
            backup = path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(path, backup)
            log.info(f"[Filesystem] Backup created: {backup}")

            header = f"\n\n# ha-mcp-plus — {datetime.now().isoformat()}"
            if comment:
                header += f"\n# {comment}"

            with open(path, "a") as f:
                f.write(header + "\n" + yaml_block + "\n")

            log.info(f"[Filesystem] Appended {len(yaml_block.splitlines())} lines to configuration.yaml")
            return {
                "success": True,
                "backup": backup,
                "lines_added": len(yaml_block.splitlines()),
                "message": "Toegevoegd aan configuration.yaml.",
                "rollback": f"Backup staat op: {backup}",
                "next_step": "Roep supervisor_reload_core() aan om de wijzigingen te activeren.",
            }

        @mcp.tool()
        def filesystem_write_file(
            relative_path: str,
            content: str,
            overwrite: bool = False,
            execute: bool = False,
        ) -> dict:
            """
            Write a file under /config.

            Shows safety analysis before writing.
            Set execute=True only after reviewing the plan.

            Args:
                relative_path: Path relative to /config.
                content: File content.
                overwrite: Allow overwriting existing files (default False).
                execute: False (default) = show plan only. True = actually write.
            """
            full_path = os.path.join(config_path, relative_path.lstrip("/"))

            if not os.path.abspath(full_path).startswith(os.path.abspath(config_path)):
                return {"success": False, "error": "Path traversal niet toegestaan"}

            exists = os.path.exists(full_path)
            if exists and not overwrite:
                return {"success": False, "error": f"Bestand bestaat al. Stel overwrite=True in: {full_path}"}

            plan = plan_write_file(relative_path, content, overwrite and exists)

            if not execute:
                return {
                    "status": "PLAN_READY",
                    "message": "Nog niets geschreven. Bekijk het plan.",
                    "plan": plan.render(),
                    "next_step": "Roep deze tool opnieuw aan met execute=True als je akkoord gaat.",
                }

            backup = None
            if exists and overwrite:
                backup = full_path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(full_path, backup)

            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)

            log.info(f"[Filesystem] Written {len(content)} bytes to {full_path}" + (f" (backup: {backup})" if backup else ""))
            return {"success": True, "path": full_path, "bytes": len(content), "backup": backup}
