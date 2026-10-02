# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""One-shot, process-verified RCON for already configured local servers.

No port is enabled, no command is retried and no connection is retained. A
matching first response confirms a receipt, not complete output or world-save
completion; the server log remains the source for the actual operation result.
"""
from __future__ import annotations

from datetime import datetime
import ipaddress
import secrets
import socket
import struct
import time

CONNECT_TIMEOUT = 3.0
AUTH_TIMEOUT = 5.0
COMMAND_TIMEOUT = 10.0
MAX_BODY_BYTES = 65536


class RconError(RuntimeError):
    pass


class RconCommandUnconfirmed(RconError):
    """The command may have executed; the caller must not retry/fall back."""


def _configuration(manager):
    try:
        values = manager.get_server_properties()
        enabled = str(values.get("enable-rcon", "false")).strip().lower() == "true"
        password = values.get("rcon.password", "")
        if not enabled or password == "":
            return None
        if not isinstance(password, str) or "\0" in password:
            raise ValueError()
        encoded = password.encode("utf-8")
        if not encoded or len(encoded) > MAX_BODY_BYTES:
            raise ValueError()
        port_text = str(values.get("rcon.port", "25575"))
        if not port_text.isascii() or not port_text.isdigit():
            raise ValueError()
        port = int(port_text)
        if not 1 <= port <= 65535:
            raise ValueError()
        address = str(values.get("server-ip", "")).strip()
        if address.startswith("[") and address.endswith("]"):
            address = address[1:-1]
        ip = ipaddress.ip_address(address or "127.0.0.1")
        if ip.is_unspecified:
            ip = ipaddress.ip_address("::1" if ip.version == 6 else "127.0.0.1")
        if ip.is_multicast or str(ip) == "255.255.255.255":
            raise ValueError()
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        # Numeric-only lookup resolves an IPv6 scope without consulting DNS.
        endpoint = socket.getaddrinfo(str(ip), port, family, socket.SOCK_STREAM,
                                      socket.IPPROTO_TCP, socket.AI_NUMERICHOST)[0][4]
        return encoded, port, family, endpoint, ip.is_loopback
    except Exception:
        raise RconError("RCON 配置无效或无法读取，未发送命令；请检查本机监听地址与 RCON 端口。") from None


def _listener_owned_by(port, pid):
    # find_pid alone returns the first row. Reject an ambiguous same-port
    # listener on another interface rather than authenticating to another PID.
    from server_manager import WindowsPortTable
    owners = set()
    for family in (socket.AF_INET, socket.AF_INET6):
        for row in WindowsPortTable._read_rows("TCP", family):
            if socket.ntohs(row.local_port & 0xFFFF) == port and row.pid:
                owners.add(int(row.pid))
    return owners == {pid}


def _set_timeout(connection, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    connection.settimeout(remaining)


def _read_exact(connection, count, deadline):
    result = bytearray()
    while len(result) < count:
        _set_timeout(connection, deadline)
        part = connection.recv(count - len(result))
        if not part:
            raise EOFError()
        result.extend(part)
    return bytes(result)


def _read_packet(connection, deadline):
    size = struct.unpack("<i", _read_exact(connection, 4, deadline))[0]
    if not 10 <= size <= MAX_BODY_BYTES + 10:
        raise ValueError()
    packet = _read_exact(connection, size, deadline)
    if packet[-2:] != b"\0\0" or b"\0" in packet[8:-2]:
        raise ValueError()
    identifier, kind = struct.unpack("<ii", packet[:8])
    text = packet[8:-2].decode("utf-8", errors="strict")
    return identifier, kind, text


def _write_packet(connection, identifier, kind, payload, deadline):
    packet = struct.pack("<ii", identifier, kind) + payload + b"\0\0"
    _set_timeout(connection, deadline)
    connection.sendall(struct.pack("<i", len(packet)) + packet)


def send_command(manager, pid, command):
    """Return a receipt string, or None only when RCON is not configured.

    Every configured failure raises RconError; never fall back to another
    transport after such a failure. An empty string is a successful receipt.
    """
    config = _configuration(manager)
    if config is None:
        return None
    if (type(pid) is not int or pid <= 0 or not isinstance(command, str)
            or not command.strip() or len(command) > 2000
            or any(character in command for character in "\r\n\0")):
        raise RconError("服务器命令或进程标识无效，未发送命令。")
    try:
        command_bytes = command.encode("utf-8", errors="strict")
        created = manager._process_creation_time(pid)
        instant = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError()
        start_ms = int(instant.timestamp() * 1000)
        if start_ms <= 0:
            raise ValueError()
    except Exception:
        raise RconError("无法确认服务器进程创建时间或命令编码，未发送命令。") from None

    from native_command_bridge import _process_guard
    password, port, family, endpoint, loopback = config
    command_started = False
    stage = "进程身份验证"
    try:
        with _process_guard(pid, start_ms) as lease:
            def validate_identity():
                if (lease.has_exited() or manager.validated_server_pid() != pid
                        or manager._process_creation_time(pid) != created
                        or not _listener_owned_by(port, pid)):
                    raise RconError("RCON 监听进程与当前服务器不一致或无法确认，未发送命令。")

            validate_identity()
            with socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP) as connection:
                stage = "本机地址验证"
                if not loopback:
                    # Binding a numeric explicit server-ip to an ephemeral port
                    # proves it belongs to this host. This never opens a listener.
                    local_endpoint = (endpoint[0], 0, *endpoint[2:])
                    connection.bind(local_endpoint)
                stage = "连接"
                connection.settimeout(CONNECT_TIMEOUT)
                connection.connect(endpoint)
                stage = "认证"
                auth_id = secrets.randbelow(0x7FFFFFFD) + 1
                command_id = auth_id + 1
                deadline = time.monotonic() + AUTH_TIMEOUT
                _write_packet(connection, auth_id, 3, password, deadline)
                for index in range(2):
                    identifier, kind, body = _read_packet(connection, deadline)
                    if identifier == -1:
                        raise RconError("RCON 认证被拒绝，未发送命令；请检查服务器当前的 RCON 配置。")
                    if identifier != auth_id or body:
                        raise ValueError()
                    if kind == 2:
                        break
                    if kind != 0 or index != 0:
                        raise ValueError()
                else:
                    raise ValueError()

                stage = "发送前进程身份验证"
                validate_identity()
                # Set this before sendall: a failed send can have transmitted a
                # complete command. Never claim it was unsent, or retry it.
                command_started = True
                deadline = time.monotonic() + COMMAND_TIMEOUT
                _write_packet(connection, command_id, 2, command_bytes, deadline)
                identifier, kind, body = _read_packet(connection, deadline)
                if identifier != command_id or kind != 0:
                    raise ValueError()
                # First valid response is the receipt. Minecraft can split long
                # output across packets; do not delay stop waiting for more.
                return body
    except Exception as error:
        if command_started:
            raise RconCommandUnconfirmed(
                "RCON 命令可能已执行，但回执尚未确认；请查看服务器日志，避免重复发送。未自动重试。") from None
        if isinstance(error, RconError):
            raise
        # Do not include raw socket errors, peer text, or credentials in errors.
        raise RconError(f"RCON {stage}失败，未发送命令；请检查服务器状态与 RCON 配置。") from None
