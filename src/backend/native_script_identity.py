# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Recognize only an immediate live Java child of this retained CMD launch."""
import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass
from pathlib import Path

from native_managed_launch import _handle_identity, _kernel


@dataclass(frozen=True)
class OwnedScriptLaunch:
    process: object
    pid: int
    birth: int
    server_id: str
    root: Path
    launcher: str
    arguments: tuple


def _expected_arguments(manager, process):
    args = tuple(process.args)
    launcher = str(manager.launch_script)
    if (Path(launcher).name != launcher or Path(launcher).suffix.lower() not in {'.bat', '.cmd'}
            or len(args) != 4 or Path(args[0]).name.lower() != 'cmd.exe'
            or args[1:3] != ('/d', '/c')
            or Path(args[3]).resolve() != (manager.server_root / launcher).resolve()):
        raise OSError('unrecognized original CMD launch arguments')
    return args


def remember_script_launch(manager, process):
    arguments = _expected_arguments(manager, process)
    pid, birth, exited = _handle_identity(_kernel(), int(process._handle))
    if pid != process.pid or not birth or exited:
        raise OSError('original CMD launch identity unavailable')
    return OwnedScriptLaunch(process, pid, birth, manager.server_id, manager.server_root.resolve(),
                             manager.launch_script, arguments)


def _same_launch(manager, owned):
    return (getattr(manager, '_owned_script_launch', None) is owned
            and manager._startup_launcher is owned.process
            and manager.server_id == owned.server_id
            and manager.server_root.resolve() == owned.root
            and manager.launch_script == owned.launcher
            and tuple(owned.process.args) == owned.arguments)


def _parent_pid(handle):
    class BasicInformation(ctypes.Structure):
        _fields_ = [('reserved1', ctypes.c_void_p), ('peb', ctypes.c_void_p),
                    ('reserved2', ctypes.c_void_p * 2), ('pid', ctypes.c_size_t),
                    ('parent_pid', ctypes.c_size_t)]
    query = ctypes.WinDLL('ntdll').NtQueryInformationProcess
    query.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    query.restype = w.LONG
    value, length = BasicInformation(), w.ULONG()
    status = query(handle, 0, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(length))
    if status != 0 or length.value < ctypes.sizeof(value) or not value.pid:
        raise OSError('native child parent identity unavailable')
    return int(value.pid), int(value.parent_pid)


def _image(kernel, handle):
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = w.BOOL
    text, length = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
    if not kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(length)):
        raise OSError('native child image unavailable')
    return Path(text.value)


def script_child_matches(manager, pid):
    """No enumeration, shell, persisted adoption or acceptance of unknown state.

    The caller still checks the listener and its ordinary Java image policy.
    Both handles are held through the comparison. An unreadable identity raises
    OSError so callers can preserve their existing conservative fallback.
    """
    owned = getattr(manager, '_owned_script_launch', None)
    if not isinstance(owned, OwnedScriptLaunch) or type(pid) is not int or pid <= 0:
        return False
    if not _same_launch(manager, owned):
        return False
    kernel = _kernel()
    parent_identity = _handle_identity(kernel, int(owned.process._handle))
    if parent_identity != (owned.pid, owned.birth, False):
        return False
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    child = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not child:
        raise OSError('native child handle unavailable')
    try:
        child_pid, birth, exited = _handle_identity(kernel, child)
        if child_pid != pid or exited or birth < owned.birth:
            return False
        actual_pid, parent_pid = _parent_pid(child)
        if actual_pid != pid or parent_pid != owned.pid:
            return False
        image = _image(kernel, child)
        if image.name.lower() not in {'java.exe', 'javaw.exe'}:
            return False
        expected = Path(manager.java_path)
        if expected.is_file() and image.resolve() != expected.resolve():
            return False
        if _handle_identity(kernel, child) != (pid, birth, False):
            return False
        return (_handle_identity(kernel, int(owned.process._handle)) == parent_identity
                and _same_launch(manager, owned))
    finally:
        kernel.CloseHandle(child)
