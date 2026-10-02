# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Build argv for the panel's unmodified launcher, without a shell relay."""
import os
from pathlib import Path
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OwnedLaunch:
    """The Popen retains the original Windows process object, even after exit."""
    process: object
    pid: int
    birth: int
    server_id: str
    root: Path
    launcher: str
    arguments: tuple


def _kernel():
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessId.argtypes = [w.HANDLE]
    kernel.GetProcessId.restype = w.DWORD
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    return kernel


def _handle_identity(kernel, handle):
    import ctypes
    from ctypes import wintypes as w
    pid = kernel.GetProcessId(handle)
    times = [w.FILETIME() for _ in range(4)]
    if not pid or not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        raise OSError("owned process identity unavailable")
    wait = kernel.WaitForSingleObject(handle, 0)
    if wait not in (0, 258):
        raise OSError("owned process wait unavailable")
    return int(pid), (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime, wait == 0


def remember_launch(manager, process):
    """Capture only a Java process just spawned through build_launch."""
    pid, birth, _ = _handle_identity(_kernel(), int(process._handle))
    if pid != process.pid or not birth:
        raise OSError("owned process identity mismatch")
    return OwnedLaunch(process, pid, birth, manager.server_id, manager.server_root.resolve(),
                       manager.launch_script, tuple(process.args))


def owned_process_pid(manager):
    """Live exact handle identity; a missing listener is never proof of exit."""
    owned = getattr(manager, '_owned_direct_launch', None)
    if not isinstance(owned, OwnedLaunch):
        return 0
    if (getattr(manager, '_startup_launcher', None) is not owned.process or manager.server_id != owned.server_id
            or manager.server_root.resolve() != owned.root or manager.launch_script != owned.launcher
            or tuple(owned.process.args) != owned.arguments):
        raise OSError('owned runtime changed during verification')
    pid, birth, exited = _handle_identity(_kernel(), int(owned.process._handle))
    if (pid, birth) != (owned.pid, owned.birth):
        raise OSError('owned runtime handle/birth mismatch')
    return 0 if exited else pid


def _native_process_rows():
    """Read a bounded native snapshot; never invoke CIM, a shell or a child tool.

    A live but unreadable relevant process remains unknown. Vanished processes
    are ignored only when their retained handle proves exit. Command lines are
    used in memory and are never included in public errors or workspace logs.
    """
    import ctypes
    from ctypes import wintypes as w
    kernel = _kernel()
    class Entry(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                    ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                    ("name", w.WCHAR * 260)]
    class UnicodeString(ctypes.Structure):
        _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", ctypes.c_void_p)]
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32FirstW.restype = w.BOOL
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
    query.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    query.restype = w.LONG
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError("native process enumeration unavailable")
    entries = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            entries.append((int(entry.pid), int(entry.parent), entry.name.lower()))
            if len(entries) > 32768:
                raise OSError("native process enumeration limit exceeded")
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES, not partial success.
            raise OSError("native process enumeration incomplete")
    finally:
        kernel.CloseHandle(snapshot)
    rows = []
    relevant = {"java.exe", "javaw.exe", "bedrock_server.exe", "php.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe"}
    for pid, parent, name in entries:
        row = {"pid": pid, "parent": parent, "name": name}
        rows.append(row)  # Keep other names for descendant relationships.
        if name not in relevant:
            continue
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # PID already vanished.
                row["exited"] = True
                continue
            raise OSError("native candidate process unreadable (pid %d)" % pid)
        try:
            actual_pid, birth, exited = _handle_identity(kernel, handle)
            if actual_pid != pid:
                raise OSError("native candidate identity mismatch")
            row.update(birth=birth, exited=exited)
            if exited:
                continue
            size = w.ULONG()
            query(handle, 60, None, 0, ctypes.byref(size))  # ProcessCommandLineInformation
            if size.value < ctypes.sizeof(UnicodeString) or size.value > 131072:
                raise OSError("native candidate command size unavailable (pid %d)" % pid)
            buffer = ctypes.create_string_buffer(size.value)
            status = query(handle, 60, buffer, size.value, ctypes.byref(size))
            if status < 0:
                if _handle_identity(kernel, handle)[2]:
                    row["exited"] = True
                    continue
                raise OSError("native candidate command unreadable (pid %d)" % pid)
            text = UnicodeString.from_buffer(buffer)
            start, end = ctypes.addressof(buffer), ctypes.addressof(buffer) + len(buffer)
            if not text.length or text.length % 2 or not text.buffer or not (start <= text.buffer <= end - text.length):
                raise OSError("native candidate command invalid (pid %d)" % pid)
            row["command"] = ctypes.wstring_at(text.buffer, text.length // 2)
            # Exit during inspection is harmless; a PID alone is never proof.
            row["exited"] = _handle_identity(kernel, handle)[2]
        finally:
            kernel.CloseHandle(handle)
    return rows


def owned_exit_snapshot(manager):
    """Return an exact owned-launch check, or None for all original/script paths.

    This deliberately does not replace the conservative general-purpose
    startup snapshot used for backups, imports, or adopted/custom servers.
    """
    result = _owned_snapshot(manager, allow_starting=False)
    if result is not None and getattr(manager, '_owned_launch_job', None) is not None:
        from native_launch_job import snapshot
        job = snapshot(manager)
        if job is None:
            raise OSError('owned job unavailable')
        result['java_pid'] = result['java_pid'] or job['java_pid']
        result['launcher_pids'] = list(set(result['launcher_pids'] + job['launcher_pids']))
    return result


def owned_startup_snapshot(manager):
    """Check the retained process even when an old startup marker remains.

    This reports process facts only. The caller must serialize state changes
    against operations and check that no startup worker is still running.
    A marker never overrides an actual live handle, child or replacement.
    """
    return _owned_snapshot(manager, allow_starting=True)


def _owned_snapshot(manager, *, allow_starting):
    owned = getattr(manager, "_owned_direct_launch", None)
    if (not isinstance(owned, OwnedLaunch) or manager._startup_launcher is not owned.process
            or manager.server_id != owned.server_id or manager.server_root.resolve() != owned.root
            or manager.launch_script != owned.launcher or tuple(owned.process.args) != owned.arguments):
        return None
    if not allow_starting and (getattr(manager, "_startup_waiting", False) or manager.starting_flag_path.exists()):
        raise OSError("owned launch still starting")
    pid, birth, exited = _handle_identity(_kernel(), int(owned.process._handle))
    if (pid, birth) != (owned.pid, owned.birth):
        raise OSError("owned launch birth/handle mismatch")
    if not exited:
        return {"java_pid": pid, "launcher_pids": [], "watchdog_pids": []}
    rows = _native_process_rows()
    descendants = {owned.pid}
    for _ in range(len(rows) + 1):
        expanded = descendants | {row["pid"] for row in rows if row["parent"] in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    marker = re.compile(r"(?:^|[\s\"])-Dqizhang\.panel\.server_id=" + re.escape(owned.server_id) + r"(?=$|[\s\"])", re.I)
    launch_paths = [str(owned.root / name).replace("/", "\\").lower()
                    for name in (owned.launcher, "qizhang-managed-start.ps1", "qizhang-platform-start.ps1")]
    from native_platforms import process_images, profile
    images = process_images(getattr(manager, 'platform', 'vanilla'))
    if profile(getattr(manager, 'platform', 'vanilla'))['runtime'] in {'native', 'php'}:
        from native_platform_launch import read
        config = read(owned.root, platform=manager.platform, server_id=manager.server_id)
        launch_paths.append(str(owned.root / config['entry']).replace('/', '\\').lower())
    watchdog_paths = [str(owned.root / name).replace("/", "\\").lower()
                      for name in ("qizhang-server-watchdog.ps1", "qizhang-server-watchdog.py", "qizhang-watchdog-launcher.ps1")]
    result = {"java_pid": 0, "launcher_pids": [], "watchdog_pids": []}
    for row in rows:
        if row.get("exited"):
            continue
        command = row.get("command", "")
        normalized = command.replace("/", "\\").lower()
        related = bool(marker.search(command) or any(path in normalized for path in launch_paths)
                       or row["pid"] in descendants)
        if related:
            if row["name"] in images:
                result["java_pid"] = row["pid"]
            else:
                result["launcher_pids"].append(row["pid"])
        if any(path in normalized for path in watchdog_paths):
            result["watchdog_pids"].append(row["pid"])
    # Ownership must still refer to this exact launch after enumeration.
    if getattr(manager, "_owned_direct_launch", None) is not owned or manager._startup_launcher is not owned.process:
        raise OSError("owned launch changed during exit verification")
    return result


def build_launch(manager):
    from native_java_bridge import resolve_launch
    return resolve_launch(manager, _build_launch(manager))


def _build_launch(manager):
    """Return (argv, environment), or None to preserve an original script.

    Only the exact templates generated by the panel opt into this path. A
    modified script keeps its existing execution semantics. Invalid owned
    configuration fails before launch and must never trigger a second attempt.
    """
    from server_manager import PanelError
    from native_platform_launch import build_launch as build_platform_launch
    native = build_platform_launch(manager)
    if native is not None:
        return native
    from native_launch_settings import (CONFIG, LAUNCHER, SCRIPT, PS_SCRIPT, _target, _read_json,
                                        inspect, _lines, _validate_jvm, managed_script, IMPORT_JVM_FILE)
    from native_server_install import inspect_java
    if manager.launch_script != LAUNCHER:
        if getattr(manager, 'hide_launcher_windows', True):
            from native_headless_launch import build_original_launch
            return build_original_launch(manager)
        return None
    root = manager.server_root
    batch = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
             f'rem -Dqizhang.panel.server_id={manager.server_id}\r\n'
             'cd /d "%~dp0"\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qizhang-managed-start.ps1" %*\r\nexit /b %errorlevel%\r\n')
    try:
        actual_batch = _target(root, LAUNCHER).read_text(encoding="utf-8-sig")
        actual_script = _target(root, SCRIPT).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None
    known_scripts = {PS_SCRIPT.replace("\r\n", "\n"), managed_script({"jvm_file": IMPORT_JVM_FILE}).replace("\r\n", "\n")}
    if actual_batch != batch.replace("\r\n", "\n") or actual_script not in known_scripts:
        return None
    try:
        saved = _read_json(_target(root, CONFIG))
        if actual_script != managed_script(saved).replace("\r\n", "\n"):
            raise PanelError("面板启动脚本与 JVM 参数配置不一致，请重新保存启动设置。")
        if (type(saved.get("schema")) is not int or saved["schema"] != 1
                or saved.get("server_id") != manager.server_id
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", str(manager.server_id))):
            raise PanelError("面板启动配置版本或实例标识无效，请检查启动设置；未运行 Java。")
        settings = inspect(manager)
        if not settings.get("supported"):
            raise PanelError(settings.get("message", "面板启动配置无效。"))
        java = Path(settings["java_path"])
        if not java.is_absolute():
            java = root / java
            if not java.resolve().is_relative_to(root.resolve()):
                raise PanelError("相对 Java 路径超出服务器目录，请重新选择 Java。")
        info = inspect_java(java, settings["java_requirement"]["major"])
        minimum = settings['java_requirement'].get('minimum_major')
        if minimum and info['major'] < minimum:
            raise PanelError('该入口至少需要 Java ' + str(minimum) + '。')
        jvm = _lines(settings["jvm_args"], "JVM 参数")
        game = _lines(settings["server_args"], "服务端参数")
        if getattr(manager, 'hide_launcher_windows', True):
            from native_headless_launch import headless_args
            game = headless_args(getattr(manager, 'platform', 'vanilla'), game)
        _validate_jvm(jvm, info["major"])
        for arg in game:
            if arg.startswith("@") or re.match(r"^(?:--(?:port|host|ip|server-ip|server-port)(?:=|\s|$)|-p)", arg, re.I):
                raise PanelError("服务端参数不能覆盖监听地址、端口或引用额外参数文件。")
        arguments = [str(info["path"]), *jvm, "-Dqizhang.panel.server_id=" + manager.server_id]
        if settings["kind"] == "args":
            if info["major"] < 9:
                raise PanelError("Java 8 不支持 @参数文件启动。")
            arguments.append("@" + settings["entry"])
        elif settings["kind"] == "classpath":
            arguments.extend(["-cp", os.pathsep.join(settings["classpath"]), settings["main_class"]])
        elif settings["kind"] == "jar":
            arguments.extend(["-jar", settings["entry"]])
        else:
            raise PanelError("面板启动入口类型无效。")
        arguments.extend(game)
        environment = os.environ.copy()
        for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
            environment.pop(key, None)
        return arguments, environment
    except PanelError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise PanelError("无法读取或验证面板启动配置，未运行 Java：" + str(error)) from None
