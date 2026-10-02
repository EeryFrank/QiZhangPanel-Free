# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
"""Real local IPC and filesystem tests. No production servers or accounts used."""
import io
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class Host:
    def __init__(self, state):
        self.responses = queue.Queue()
        self.process = subprocess.Popen([sys.executable, "-B", str(ROOT / "src/native-host.py"), "--data-root", str(state)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def read():
            for line in self.process.stdout:
                self.responses.put(json.loads(line))
        self.worker = threading.Thread(target=read, daemon=True)
        self.worker.start()

    def request(self, action, payload=None, ok=True):
        self.process.stdin.write(json.dumps({"action": action, "payload": payload or {}}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        reply = self.responses.get(timeout=40)
        if reply["ok"] is not ok:
            raise AssertionError(reply)
        return reply.get("data") if ok else reply["error"]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process.stdout.close()
        self.process.stderr.close()


@unittest.skipUnless(os.name == "nt", "Windows process and ACL integration")
class FreeHostTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("QIZHANG_CACHE_ROOT", tempfile.gettempdir())) / "free-host-tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="中文 smoke-", dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = Host(self.root / "state")
        self.addCleanup(self.host.close)
        self.host.request("register", {"username": "单服测试", "password": "Isolated-Free-Test-123"})

    def fixture(self, name="服务器 中文"):
        server = self.root / name
        server.mkdir()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        (server / "run.bat").write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
        (server / "server.properties").write_text(f"server-ip=127.0.0.1\nserver-port={port}\nlevel-name=world\n", encoding="utf-8")
        (server / "world").mkdir()
        (server / "world/level.dat").write_bytes(b"offline-test-world")
        (server / "world/region").mkdir()
        (server / "world/region/r.0.0.mca").write_bytes(b"chunk-fixture")
        return server

    def bind(self, server):
        return self.host.request("servers.add", {"id": "one", "name": "测试服", "platform": "vanilla", "path": str(server), "launch_script": "run.bat"})

    def idle(self):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            status = self.host.request("status")
            if not status.get("operation", {}).get("active") and status.get("server", {}).get("status_known"):
                return status
            time.sleep(.1)
        self.fail("Host did not become idle")

    def test_single_binding_accounts_settings_and_safe_exit(self):
        self.assertEqual(self.host.request("hello")["edition"]["name"], "free")
        server = self.fixture()
        self.bind(server)
        self.assertEqual(len(self.host.request("servers.list")["servers"]), 1)
        self.assertIn("免费版", self.host.request("servers.add", {"path": str(self.fixture("other"))}, ok=False))
        self.idle()
        settings = self.host.request("settings.get")
        self.assertIn("poll_seconds", settings["panel"])
        self.host.request("settings.update", {"panel": {"poll_seconds": 1}})
        self.assertEqual(self.host.request("settings.get")["panel"]["poll_seconds"], 1)
        self.host.request("logout")
        self.host.request("login", {"username": "单服测试", "password": "Isolated-Free-Test-123"})
        self.assertEqual(len(self.host.request("servers.list")["servers"]), 1)
        self.assertTrue(self.host.request("panel.exit")["all_stopped"])

    def backup_roundtrip(self, mode):
        server = self.fixture()
        self.bind(server)
        self.idle()
        self.host.request("backups.create", {"mode": mode})
        state = self.idle()
        self.assertTrue(state["operation"]["ok"], state["operation"])
        backups = self.host.request("backups.list")["backups"]
        self.assertEqual(len(backups), 1)
        name = backups[0].get("filename", backups[0].get("name"))
        (server / "world/level.dat").write_bytes(b"changed")
        self.host.request("backups.restore", {"filename": name, "confirm": name, "restart_after": False})
        state = self.idle()
        self.assertTrue(state["operation"]["ok"], state["operation"])
        self.assertEqual((server / "world/level.dat").read_bytes(), b"offline-test-world")
        self.host.request("servers.remove", {"id": "one"})
        self.assertTrue(server.is_dir())
        self.assertEqual(self.host.request("servers.list")["servers"], [])

    def test_manual_backup_restore_keeps_source_folder(self):
        self.backup_roundtrip("full")

    def test_offline_light_backup_restore_keeps_source_folder(self):
        self.backup_roundtrip("light")

    def test_zip_import_uses_native_platform_without_java(self):
        source = self.root / "隔离基岩.zip"
        with zipfile.ZipFile(source, "w") as z:
            z.writestr("server/bedrock_server.exe", b"MZ-inert-test-fixture")
            z.writestr("server/server.properties", "server-port=19132\n")
        target = self.root / "解压服务器"
        self.host.request("server.archive.start", {"archive": str(source), "path": str(target), "name": "基岩导入", "adapt_startup": True})
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            job = self.host.request("server.install.status")
            if not job.get("active"):
                break
            time.sleep(.1)
        self.assertEqual(job.get("phase"), "complete", job)
        self.assertEqual(self.host.request("servers.list")["servers"][0]["platform"], "bedrock")
        self.assertTrue((target / "qizhang-platform-launch.json").is_file())
        self.assertFalse((target / "eula.txt").exists())


if __name__ == "__main__":
    unittest.main()
