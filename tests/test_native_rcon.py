"""Real loopback protocol fixtures; identity checks are separately exercised.

Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
import native_rcon as rcon
import native_command_bridge as bridge
from server_manager import WindowsPortTable


def packet(identifier, kind, body=b""):
    if isinstance(body, str):
        body = body.encode("utf-8")
    payload = struct.pack("<ii", identifier, kind) + body + b"\0\0"
    return struct.pack("<i", len(payload)) + payload


def receive(connection):
    def read(count):
        data = b""
        while len(data) < count:
            part = connection.recv(count - len(data))
            if not part:
                raise EOFError()
            data += part
        return data
    size = struct.unpack("<i", read(4))[0]
    data = read(size)
    return (*struct.unpack("<ii", data[:8]), data[8:-2].decode("utf-8"))


class RconTests(unittest.TestCase):
    def setUp(self):
        self.properties = {"enable-rcon": "true", "rcon.password": "private-口令-fixture",
                           "server-ip": "127.0.0.1", "rcon.port": "25575"}
        self.manager = SimpleNamespace(
            get_server_properties=Mock(side_effect=lambda: dict(self.properties)),
            validated_server_pid=Mock(return_value=123),
            _process_creation_time=Mock(return_value="2026-09-29T00:00:00+00:00"))
        self.lease = SimpleNamespace(has_exited=Mock(return_value=False))
        self.guard_active = False
        self.guard_finished = False
        self.requests = []
        self.thread_errors = []

        @contextmanager
        def guard(pid, timestamp):
            self.assertEqual(pid, 123)
            self.assertEqual(timestamp, int(datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp() * 1000))
            self.guard_active = True
            try:
                yield self.lease
            finally:
                self.guard_active = False
                self.guard_finished = True

        self.guard = patch.object(bridge, "_process_guard", side_effect=guard)
        self.guard_mock = self.guard.start()
        self.addCleanup(self.guard.stop)
        owner_patch = patch.object(rcon, "_listener_owned_by", side_effect=self.owner)
        self.owner_mock = owner_patch.start()
        self.addCleanup(owner_patch.stop)
        for name in ("CONNECT_TIMEOUT", "AUTH_TIMEOUT", "COMMAND_TIMEOUT"):
            patcher = patch.object(rcon, name, .3)
            patcher.start()
            self.addCleanup(patcher.stop)

    def owner(self, port, pid):
        self.assertTrue(self.guard_active)
        self.assertEqual(pid, 123)
        return True

    def request(self, connection):
        value = receive(connection)
        self.requests.append(value)
        return value

    @contextmanager
    def server(self, handler, ipv6=False):
        family = socket.AF_INET6 if ipv6 else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(("::1" if ipv6 else "127.0.0.1", 0))
            except OSError:
                if ipv6:
                    self.skipTest("IPv6 loopback unavailable")
                raise
            listener.listen(1)
            listener.settimeout(1)
            self.properties["rcon.port"] = str(listener.getsockname()[1])

            def serve():
                try:
                    with listener.accept()[0] as connection:
                        connection.settimeout(1)
                        handler(connection)
                except (EOFError, BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
                    pass
                except Exception as error:
                    self.thread_errors.append(error)

            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            try:
                yield
            finally:
                worker.join(2)
                self.assertFalse(worker.is_alive(), "fixture must not leave a thread")
                if self.thread_errors:
                    raise self.thread_errors[0]

    def authenticate(self, connection, preliminary=False):
        identifier, kind, body = self.request(connection)
        self.assertEqual((kind, body), (3, self.properties["rcon.password"]))
        if preliminary:
            connection.sendall(packet(identifier, 0))
        connection.sendall(packet(identifier, 2))

    def send(self, command="say 你好"):
        return rcon.send_command(self.manager, 123, command)

    def test_authenticated_unicode_single_command_and_guard_lifetime(self):
        def handle(connection):
            self.authenticate(connection, preliminary=True)
            identifier, kind, body = self.request(connection)
            self.assertEqual((kind, body), (2, "say 你好"))
            self.assertTrue(self.guard_active)
            for byte in packet(identifier, 0, "收到：你好"):
                connection.sendall(bytes([byte]))
            self.assertEqual(connection.recv(1), b"", "must close without probe/retry")
        with self.server(handle):
            self.assertEqual(self.send(), "收到：你好")
        self.assertEqual([row[1] for row in self.requests], [3, 2])
        self.assertTrue(self.guard_finished)
        self.assertEqual(self.owner_mock.call_count, 2)

    def test_empty_response_is_success_not_unconfigured(self):
        def handle(connection):
            self.authenticate(connection)
            identifier, _, _ = self.request(connection)
            connection.sendall(packet(identifier, 0))
        with self.server(handle):
            self.assertEqual(self.send("stop"), "")

    def test_returns_first_receipt_without_waiting_for_multiframe_output(self):
        def handle(connection):
            self.authenticate(connection)
            identifier, _, _ = self.request(connection)
            connection.sendall(packet(identifier, 0, "first") + packet(identifier, 0, "second"))
        with self.server(handle):
            self.assertEqual(self.send(), "first")

    def test_ipv6_loopback(self):
        self.properties["server-ip"] = "::1"
        def handle(connection):
            self.authenticate(connection)
            identifier, _, _ = self.request(connection)
            connection.sendall(packet(identifier, 0, "v6"))
        with self.server(handle, ipv6=True):
            self.assertEqual(self.send(), "v6")

    def test_disabled_or_empty_password_never_creates_connection(self):
        with patch.object(rcon.socket, "socket") as factory:
            for change in ({"enable-rcon": "false"}, {"rcon.password": ""}):
                original = dict(self.properties)
                self.properties.update(change)
                self.assertIsNone(self.send())
                self.properties = original
            factory.assert_not_called()
        self.guard_mock.assert_not_called()

    def test_malformed_configuration_never_falls_back(self):
        for change in ({"rcon.port": "0"}, {"rcon.port": "65536"}, {"rcon.port": "1.5"},
                       {"rcon.port": "１２３"}, {"server-ip": "example.invalid"},
                       {"server-ip": "224.0.0.1"}, {"rcon.password": "x\0y"}):
            with self.subTest(change={key: "invalid" for key in change}):
                original = dict(self.properties)
                self.properties.update(change)
                with self.assertRaises(rcon.RconError):
                    self.send()
                self.properties = original
        self.guard_mock.assert_not_called()

    def test_config_error_does_not_expose_secret(self):
        self.manager.get_server_properties.side_effect = RuntimeError(self.properties["rcon.password"])
        with self.assertRaises(rcon.RconError) as caught:
            self.send()
        self.assertNotIn(self.properties["rcon.password"], str(caught.exception))

    def test_wildcard_is_converted_to_loopback(self):
        for configured, expected in (("", "127.0.0.1"), ("0.0.0.0", "127.0.0.1"), ("::", "::1")):
            self.properties["server-ip"] = configured
            self.assertEqual(rcon._configuration(self.manager)[3][0], expected)

    def test_explicit_nonlocal_address_is_rejected_before_authentication(self):
        self.properties["server-ip"] = "203.0.113.254"
        with self.assertRaises(rcon.RconError) as caught:
            self.send()
        self.assertIn("本机地址验证", str(caught.exception))
        self.assertNotIsInstance(caught.exception, rcon.RconCommandUnconfirmed)

    def test_wrong_listener_or_reused_pid_never_connects(self):
        for change in ("listener", "pid", "lease", "creation"):
            with self.subTest(change=change), patch.object(rcon.socket, "socket") as factory:
                self.owner_mock.side_effect = self.owner
                self.manager.validated_server_pid.return_value = 123
                self.manager._process_creation_time.side_effect = None
                self.lease.has_exited.return_value = False
                if change == "listener":
                    self.owner_mock.side_effect = None
                    self.owner_mock.return_value = False
                elif change == "pid":
                    self.manager.validated_server_pid.return_value = 456
                elif change == "lease":
                    self.lease.has_exited.return_value = True
                else:
                    self.manager._process_creation_time.side_effect = ["2026-09-29T00:00:00+00:00", "2026-09-29T00:00:01+00:00"]
                with self.assertRaises(rcon.RconError):
                    self.send()
                factory.assert_not_called()

    def test_identity_changed_after_authentication_sends_no_command(self):
        self.owner_mock.side_effect = [True, False]
        def handle(connection):
            self.authenticate(connection)
            self.assertEqual(connection.recv(1), b"")
        with self.server(handle), self.assertRaises(rcon.RconError) as caught:
            self.send()
        self.assertNotIsInstance(caught.exception, rcon.RconCommandUnconfirmed)
        self.assertEqual(len(self.requests), 1)

    def test_authentication_rejection_never_sends_command(self):
        def handle(connection):
            self.request(connection)
            connection.sendall(packet(-1, 2))
            self.assertEqual(connection.recv(1), b"")
        with self.server(handle), self.assertRaises(rcon.RconError) as caught:
            self.send()
        self.assertIn("认证被拒绝", str(caught.exception))
        self.assertEqual(len(self.requests), 1)

    def test_invalid_auth_packets_never_send_command(self):
        generators = [lambda i: packet(i + 1, 2), lambda i: packet(i, 2, "unexpected"),
                      lambda i: packet(i, 3), lambda i: packet(i, 0) + packet(i, 0),
                      lambda i: struct.pack("<i", -1), lambda i: struct.pack("<i", 9),
                      lambda i: struct.pack("<i", rcon.MAX_BODY_BYTES + 11),
                      lambda i: packet(i, 2, b"\xff"), lambda i: packet(i, 2)[:-2] + b"xx"]
        for generate in generators:
            with self.subTest(index=generators.index(generate)):
                self.requests.clear()
                def handle(connection):
                    identifier, _, _ = self.request(connection)
                    connection.sendall(generate(identifier))
                with self.server(handle), self.assertRaises(rcon.RconError) as caught:
                    self.send()
                self.assertNotIsInstance(caught.exception, rcon.RconCommandUnconfirmed)
                self.assertEqual(len(self.requests), 1)

    def test_command_receipt_failures_are_unconfirmed_without_retry(self):
        generators = [lambda i: b"", lambda i: packet(i + 1, 0), lambda i: packet(i, 2),
                      lambda i: packet(-1, 0), lambda i: packet(i, 0, b"\xff"),
                      lambda i: packet(i, 0, b"a\0b"), lambda i: packet(i, 0)[:-1],
                      lambda i: struct.pack("<i", rcon.MAX_BODY_BYTES + 11)]
        for generate in generators:
            with self.subTest(index=generators.index(generate)):
                self.requests.clear()
                def handle(connection):
                    self.authenticate(connection)
                    identifier, _, _ = self.request(connection)
                    connection.sendall(generate(identifier))
                with self.server(handle), self.assertRaises(rcon.RconCommandUnconfirmed) as caught:
                    self.send()
                self.assertIn("未自动重试", str(caught.exception))
                self.assertNotIn(self.properties["rcon.password"], str(caught.exception))
                self.assertEqual([row[1] for row in self.requests], [3, 2])

    def test_command_send_failure_is_also_unconfirmed(self):
        real_write = rcon._write_packet
        def write(connection, identifier, kind, payload, deadline):
            if kind == 2:
                raise OSError("partial transmission " + self.properties["rcon.password"])
            return real_write(connection, identifier, kind, payload, deadline)
        def handle(connection):
            self.authenticate(connection)
        with self.server(handle), patch.object(rcon, "_write_packet", side_effect=write):
            with self.assertRaises(rcon.RconCommandUnconfirmed) as caught:
                self.send()
        self.assertNotIn(self.properties["rcon.password"], str(caught.exception))

    def test_auth_and_command_timeouts_have_distinct_diagnostics(self):
        for after_auth in (False, True):
            with self.subTest(after_auth=after_auth):
                def handle(connection):
                    if after_auth:
                        self.authenticate(connection)
                        self.request(connection)
                    else:
                        self.request(connection)
                    time.sleep(.4)
                with self.server(handle), self.assertRaises(rcon.RconError) as caught:
                    self.send()
                self.assertEqual(isinstance(caught.exception, rcon.RconCommandUnconfirmed), after_auth)

    def test_fragmented_auth_has_total_deadline(self):
        def handle(connection):
            identifier, _, _ = self.request(connection)
            for byte in packet(identifier, 2):
                connection.sendall(bytes([byte]))
                time.sleep(.06)
        with self.server(handle), self.assertRaises(rcon.RconError) as caught:
            self.send()
        self.assertNotIsInstance(caught.exception, rcon.RconCommandUnconfirmed)
        self.assertEqual(len(self.requests), 1)

    def test_response_body_bound_accepts_exact_limit(self):
        def handle(connection):
            self.authenticate(connection)
            identifier, _, _ = self.request(connection)
            connection.sendall(packet(identifier, 0, b"a" * rcon.MAX_BODY_BYTES))
        with self.server(handle):
            self.assertEqual(len(self.send()), rcon.MAX_BODY_BYTES)


class ListenerIdentityTests(unittest.TestCase):
    def test_port_owners_must_agree_across_interfaces_and_families(self):
        row = lambda pid, port=25575: SimpleNamespace(pid=pid, local_port=socket.htons(port))
        for rows, expected in (([[row(123)], []], True), ([[row(123)], [row(123)]], True),
                               ([[row(123)], [row(456)]], False), ([[], []], False),
                               ([[row(123, 25565)], []], False)):
            with patch.object(WindowsPortTable, "_read_rows", side_effect=rows):
                self.assertEqual(rcon._listener_owned_by(25575, 123), expected)

    @unittest.skipUnless(os.name == "nt", "Windows process/table integration")
    def test_real_windows_handle_and_listener_ownership_with_inert_process(self):
        # This Python process is the inert target, not a Minecraft server.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
        kernel.GetProcessTimes.restype = wintypes.BOOL
        created, exited, kt, ut = (wintypes.FILETIME() for _ in range(4))
        self.assertTrue(kernel.GetProcessTimes(kernel.GetCurrentProcess(),
                                              *map(ctypes.byref, (created, exited, kt, ut))))
        timestamp = (((created.dwHighDateTime << 32) | created.dwLowDateTime) - 116444736000000000) // 10000
        iso = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()
        requests, errors = [], []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            port = listener.getsockname()[1]
            def serve():
                try:
                    with listener.accept()[0] as connection:
                        connection.settimeout(5)
                        identifier, kind, text = receive(connection)
                        requests.append((kind, text))
                        connection.sendall(packet(identifier, 2))
                        identifier, kind, text = receive(connection)
                        requests.append((kind, text))
                        connection.sendall(packet(identifier, 0, "owned"))
                except Exception as error:
                    errors.append(error)
            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            manager = SimpleNamespace(
                get_server_properties=lambda: {"enable-rcon": "true", "rcon.password": "fixture-only",
                                               "server-ip": "127.0.0.1", "rcon.port": str(port)},
                validated_server_pid=lambda: os.getpid(), _process_creation_time=lambda pid: iso)
            try:
                self.assertEqual(rcon.send_command(manager, os.getpid(), "list"), "owned")
            finally:
                worker.join(6)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(requests, [(3, "fixture-only"), (2, "list")])


if __name__ == "__main__":
    unittest.main()
