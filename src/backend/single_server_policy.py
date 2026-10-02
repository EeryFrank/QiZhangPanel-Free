# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
"""One local server binding; this distribution has no upgrade or edition switch."""
import json
import threading
from pathlib import Path
from server_manager import PanelError, atomic_write_json


class SingleServerPolicy:
    def __init__(self, state_root):
        self.slot_path = Path(state_root) / "edition-slot.json"
        self.lock = threading.RLock()
        self.slot = None
        self.slot_error = ""
        if self.slot_path.exists():
            try:
                document = json.loads(self.slot_path.read_text(encoding="utf-8-sig"))
                if not isinstance(document, dict) or document.get("schema") != 1:
                    raise ValueError()
                binding = document.get("binding")
                if binding is not None and (not isinstance(binding, dict) or
                    not isinstance(binding.get("account_id"), str) or not binding["account_id"] or
                    not isinstance(binding.get("server_id"), str) or not binding["server_id"]):
                    raise ValueError()
                self.slot = binding
            except (OSError, ValueError, UnicodeError):
                self.slot_error = "服务器绑定记录无法读取，请保留原文件并恢复 edition-slot.json。"

    def describe(self, account_id=None):
        result = {"name": "free", "label": "免费版", "features": ["single_server", "server_install", "console", "basic_settings", "manual_backups", "shutdown_notice", "panel_autostart"],
                  "server_limit": 1, "slot_assigned": bool(self.slot), "slot_error": self.slot_error}
        if self.slot and account_id == self.slot["account_id"]:
            result["selected_server_id"] = self.slot["server_id"]
        elif self.slot:
            result["slot_owned_by_another_account"] = True
        return result

    def owns(self, account_id, server_id):
        return not self.slot_error and self.slot == {"account_id": str(account_id), "server_id": str(server_id)}

    def require_server(self, account_id, server_id):
        if self.slot_error:
            raise PanelError(self.slot_error)
        if not self.owns(account_id, server_id):
            raise PanelError("这台服务器未占用唯一管理槽位。请先在服务器列表选择服务器。")

    def bind(self, account_id, server_id):
        with self.lock:
            if self.slot_error:
                raise PanelError(self.slot_error)
            binding = {"account_id": str(account_id), "server_id": str(server_id)}
            if self.slot and self.slot != binding:
                raise PanelError("服务器槽位已使用。移除原服务器绑定后才能选择另一台，服务器文件不会删除。")
            atomic_write_json(self.slot_path, {"schema": 1, "binding": binding})
            self.slot = binding

    def release(self, account_id, server_id):
        with self.lock:
            if self.owns(account_id, server_id):
                atomic_write_json(self.slot_path, {"schema": 1, "binding": None})
                self.slot = None

    def check_action(self, action, payload):
        if action == "settings.update":
            panel = payload.get("panel", {})
            if not isinstance(panel, dict) or set(panel) - {"poll_seconds"}:
                raise PanelError("仅可修改基础服务器设置和刷新间隔。")
