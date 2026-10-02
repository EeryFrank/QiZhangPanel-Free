# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
from server_manager import ServerManager, PanelError


class OfflineBackupGuardTests(unittest.TestCase):
    def manager(self, pid=0, snapshot=None):
        return SimpleNamespace(ensure_not_starting=Mock(), validated_server_pid=Mock(return_value=pid),
            _startup_process_snapshot=Mock(return_value=snapshot))

    def test_running_server_rejected_before_file_work(self):
        manager = self.manager(pid=123)
        with self.assertRaisesRegex(PanelError, "停止服务器"):
            ServerManager._require_stopped_for_backup(manager)
        manager.validated_server_pid.assert_called_once_with(strict=True)
        manager._startup_process_snapshot.assert_not_called()

    def test_unknown_or_launcher_only_activity_rejected(self):
        for value in (None, {}, {"java_pid": None, "launcher_pids": [], "watchdog_pids": []},
                      {"java_pid": 0, "launcher_pids": [123], "watchdog_pids": []}):
            with self.subTest(snapshot=value), self.assertRaises(PanelError):
                ServerManager._require_stopped_for_backup(self.manager(snapshot=value))

    def test_verified_empty_snapshot_accepted(self):
        manager = self.manager(snapshot={"java_pid": 0, "launcher_pids": [], "watchdog_pids": []})
        ServerManager._require_stopped_for_backup(manager)
        manager._startup_process_snapshot.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
