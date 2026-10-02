# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""On-demand command helper for imported Bukkit/CatServer/Forge processes.

The helper is shipped with the panel, not expected in arbitrary server ZIPs.
It queues commands on the server's own console queue. Nothing is installed into
the server, no listening port is opened, and no command is retried automatically.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from native_server_install import discover_java, inspect_java, ServerInstallError

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AGENT_JAR = Path(__file__).resolve().parent / "tools/command-agent/build/qizhang-command-agent-v3.jar"
_cache = {}
_cache_lock = threading.Lock()


class CommandBridgeError(RuntimeError):
    pass


class _ProcessLease:
    def __init__(self, kernel, handle):
        self._kernel, self._handle = kernel, handle

    def has_exited(self):
        status = self._kernel.WaitForSingleObject(self._handle, 0)
        if status == 0:
            return True
        if status == 0x102:
            return False
        raise CommandBridgeError("无法确认原服务器进程是否已退出。")


@contextmanager
def _process_guard(pid, expected_start_ms):
    """Pin the actual Windows process object for the complete attach operation.

    OS creation time is compared with the same OS clock, never the later Java
    RuntimeMXBean initialization time. The retained kernel handle also prevents
    the original process identity from being confused with a reused PID.
    """
    if os.name != "nt":
        raise CommandBridgeError("此命令组件需要 Windows 进程身份验证。")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not handle:
        raise CommandBridgeError("无法锁定服务器进程身份，未发送命令；请检查面板与服务器的运行权限。")
    try:
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, *map(ctypes.byref, (created, exited, kernel_time, user_time))):
            raise CommandBridgeError("无法读取服务器进程创建时间，未发送命令。")
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        actual_start_ms = (ticks - 116444736000000000) // 10000
        if abs(actual_start_ms - expected_start_ms) > 1 or kernel.WaitForSingleObject(handle, 0) != 0x102:
            raise CommandBridgeError("发送前服务器进程已退出或身份发生变化，未发送命令。")
        yield _ProcessLease(kernel, handle)
    finally:
        kernel.CloseHandle(handle)


def _environment():
    values = os.environ.copy()
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        values.pop(name, None)
    return values


def _base_command(info, jar):
    java = Path(info["path"])
    major = info["major"]
    classpath = [str(jar)]
    flags = []
    if major < 9:
        homes = [java.parent.parent, java.parent.parent.parent]
        tools = next((home / "lib/tools.jar" for home in homes if (home / "lib/tools.jar").is_file()), None)
        if tools is not None:
            classpath.append(str(tools))
    else:
        flags = ["--add-modules", "jdk.attach"]
    return [str(java), *flags, "-Dfile.encoding=UTF-8",
            "-cp", os.pathsep.join(classpath), "QiZhangAgentLoader"]


def _run(arguments, *, cwd=None, timeout=15):
    return subprocess.run(arguments, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=_environment(), creationflags=NO_WINDOW, timeout=timeout, check=False)


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value or "")


def _failure_message(result):
    detail = (_text(result.stderr) or _text(result.stdout)).strip()[:1800]
    rejected = detail.startswith("QIZHANG_COMMAND_REJECTED: ")
    stages = {
        "helper": "命令辅助程序检查", "attach": "连接服务器 Java",
        "identity": "核对服务器进程与目录", "payload": "校验命令数据",
        "command": "校验命令内容", "lookup": "识别运行中的服务器核心",
        "queue_lookup": "查找核心命令接口", "queue": "提交核心命令",
        "agent_load": "加载命令组件", "receipt": "读取命令回执",
    }
    match = re.search(r"\bstage=([a-z_]+)\b", detail)
    phase = stages.get(match[1], match[1]) if match else ""
    message = ("内置命令通道拒绝了本次请求，命令未进入服务器队列。"
               if rejected else "内置命令通道未确认提交；请检查服务器状态与日志，避免重复发送。")
    if phase:
        message += " 失败阶段：" + phase + "。"
    message += " 未自动重试。"
    return message + (" 技术详情：" + detail if detail else " 返回码：" + str(result.returncode))


def _select_helper(preferred_java, jar):
    key = (os.path.normcase(str(preferred_java)), str(jar), jar.stat().st_mtime_ns)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() < cached[0] and Path(cached[1][0]).is_file():
            return list(cached[1])
    seen = set()
    # Probe the server runtime first. A Java 8 JRE may lack Attach; a separate
    # installed JDK can run the helper without changing the server's Java.
    for candidates in ([str(preferred_java)], None):
        if candidates is None:
            candidates = discover_java()
        for candidate in candidates:
            identity = os.path.normcase(str(candidate))
            if identity in seen:
                continue
            seen.add(identity)
            try:
                info = inspect_java(candidate)
                arguments = _base_command(info, jar)
                probe = _run([*arguments, "--probe"], timeout=10)
                if probe.returncode != 0 or _text(probe.stdout).strip() != "QIZHANG_ATTACH_AVAILABLE":
                    continue
            except (OSError, ValueError, ServerInstallError, subprocess.TimeoutExpired):
                continue
            with _cache_lock:
                if len(_cache) >= 16:
                    _cache.clear()
                _cache[key] = (time.monotonic() + 60, tuple(arguments))
            return arguments
    raise CommandBridgeError(
        "没有可用的 64 位 JDK 命令辅助运行环境。当前服务器 Java 可能只有 JRE；"
        "请安装 64 位 JDK 8 或更新版本后重试。面板会单独使用它发送命令，不会更换服务器的 Java。")


def send_command(manager, pid, command):
    if (type(pid) is not int or pid <= 0 or not isinstance(command, str)
            or not command.strip() or len(command) > 2000 or any(c in command for c in "\r\n\0")):
        raise CommandBridgeError("服务器命令或进程标识无效。")
    jar = AGENT_JAR
    if not jar.is_file():
        raise CommandBridgeError("面板内置命令组件不完整，请使用完整安装包升级面板；无需重新导入服务器。")
    created = manager._process_creation_time(pid)
    try:
        start_ms = int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() * 1000)
        if start_ms <= 0:
            raise ValueError()
    except (ValueError, AttributeError, OverflowError):
        raise CommandBridgeError("无法确认服务器进程的启动时间，未发送命令。") from None
    arguments = _select_helper(manager.java_path, jar)
    # Discover/probe can take time. Check the original lifetime again, then pin
    # that exact kernel object while the agent checks the target root and PID.
    if (manager.validated_server_pid() != pid
            or manager._process_creation_time(pid) != created):
        raise CommandBridgeError("发送前服务器进程已改变，请刷新状态后重试。")
    root = str(manager.server_root.resolve())
    encode = lambda value: base64.b64encode(value.encode("utf-8")).decode("ascii")
    try:
        with _process_guard(pid, start_ms):
            result = _run([*arguments, str(pid), str(jar), encode(command), encode(root), str(start_ms)],
                          cwd=root, timeout=20)
    except subprocess.TimeoutExpired:
        raise CommandBridgeError("等待命令通道回执超时；执行结果尚未确认，请查看服务器日志，避免重复发送。") from None
    except OSError as error:
        raise CommandBridgeError("无法启动内置命令辅助程序：" + str(error)) from error
    if result.returncode != 0 or "QIZHANG_COMMAND_QUEUED" not in _text(result.stdout).splitlines():
        raise CommandBridgeError(_failure_message(result))
