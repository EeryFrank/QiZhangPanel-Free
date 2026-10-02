# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Track an original launcher's whole Windows process tree without killing it.

The root is assigned while suspended, before it can create a GUI/Java child.
No KILL_ON_JOB_CLOSE, UI restrictions, timer, watcher thread or helper process
is installed. Unknown queries are errors, never an empty process tree.
"""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess

from native_managed_launch import _handle_identity, _kernel


def _api():
    kernel = _kernel()
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.QueryInformationJobObject.restype = w.BOOL
    kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    kernel.IsProcessInJob.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = w.BOOL
    kernel.ResumeThread.argtypes = [w.HANDLE]
    kernel.ResumeThread.restype = w.DWORD
    return kernel


class ScriptProcess:
    """The Popen interface used by ServerManager, retaining the process handle."""
    stdin = None

    def __init__(self, handle, pid, arguments):
        self._handle = subprocess.Handle(handle)
        self.pid, self.args, self.returncode = pid, list(arguments), None

    def poll(self):
        import _winapi
        if self.returncode is None and _winapi.WaitForSingleObject(int(self._handle), 0) == _winapi.WAIT_OBJECT_0:
            self.returncode = _winapi.GetExitCodeProcess(int(self._handle))
        return self.returncode

    def wait(self, timeout=None):
        import _winapi
        delay = _winapi.INFINITE if timeout is None else max(0, int(timeout * 1000))
        if _winapi.WaitForSingleObject(int(self._handle), delay) == _winapi.WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.poll()


@dataclass
class LaunchJob:
    handle: object
    process: ScriptProcess
    birth: int
    server_id: str
    root: Path
    launcher: str
    arguments: tuple
    desktop: object


def _create_process(kernel, arguments, environment, directory, handles, desktop):
    # CPython STARTUPINFO exposes only part of STARTUPINFO; use the documented
    # Win32 structure here so lpDesktop is actually passed to CreateProcessW.
    class Startup(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
                    ("x", w.DWORD), ("y", w.DWORD), ("width", w.DWORD), ("height", w.DWORD),
                    ("chars_x", w.DWORD), ("chars_y", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                    ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_data", ctypes.c_void_p),
                    ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]
    class Extended(ctypes.Structure):
        _fields_ = [("startup", Startup), ("attributes", ctypes.c_void_p)]
    class Information(ctypes.Structure):
        _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]
    kernel.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.InitializeProcThreadAttributeList.restype = w.BOOL
    kernel.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                                ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel.UpdateProcThreadAttribute.restype = w.BOOL
    kernel.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                                     ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(Extended), ctypes.POINTER(Information)]
    kernel.CreateProcessW.restype = w.BOOL
    length = ctypes.c_size_t()
    kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(length))
    if not 0 < length.value <= 65536:
        raise OSError("process attribute buffer unavailable")
    attributes = ctypes.create_string_buffer(length.value)
    if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(length)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        inherited = (w.HANDLE * len(handles))(*handles)
        if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020002, inherited, ctypes.sizeof(inherited), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        info, result = Extended(), Information()
        info.startup.cb = ctypes.sizeof(Extended)
        info.startup.desktop = desktop
        info.startup.flags = 0x100 | 1  # USESTDHANDLES | USESHOWWINDOW (SW_HIDE)
        info.startup.stdin, info.startup.stdout, info.startup.stderr = handles
        info.attributes = ctypes.addressof(attributes)
        block = None
        if environment is not None:
            if any("\0" in str(key) or "\0" in str(value) for key, value in environment.items()):
                raise ValueError("invalid launcher environment")
            block = ctypes.create_unicode_buffer("\0".join(str(key) + "=" + str(value)
                for key, value in sorted(environment.items(), key=lambda item: item[0].upper())) + "\0\0")
        flags = subprocess.CREATE_NO_WINDOW | 0x4 | 0x400 | 0x80000
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
        if not kernel.CreateProcessW(None, command, None, None, True, flags, block, str(directory),
                                     ctypes.byref(info), ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(result.process), int(result.thread), int(result.pid)
    finally:
        kernel.DeleteProcThreadAttributeList(attributes)


def start_script(manager, arguments, environment, stdout, stderr):
    return start_process(manager, arguments, environment, stdout, stderr)


def start_process(manager, arguments, environment, stdout, stderr, *, pipe_input=False, cwd=None):
    """Create exactly one original CMD launch, assigned before any instruction."""
    import _winapi
    import msvcrt
    kernel = _api()
    raw_job = kernel.CreateJobObjectW(None, None)
    if not raw_job:
        raise ctypes.WinError(ctypes.get_last_error())
    job_handle = subprocess.Handle(raw_job)
    from native_hidden_desktop import HiddenDesktop
    desktop = None
    duplicates = []
    process = None
    parent_input = None
    read_input = None
    thread = None
    resumed = False
    try:
        if getattr(manager, 'hide_launcher_windows', True):
            desktop = HiddenDesktop()
        if pipe_input:
            read_fd, write_fd = os.pipe()
            read_input = os.fdopen(read_fd, 'rb', buffering=0)
            parent_input = os.fdopen(write_fd, 'wb', buffering=0)
        else:
            read_input = open(os.devnull, 'rb')
        with read_input as stdin:
            current = _winapi.GetCurrentProcess()
            for file in (stdin, stdout, stderr):
                duplicates.append(_winapi.DuplicateHandle(current, msvcrt.get_osfhandle(file.fileno()),
                    current, 0, True, _winapi.DUPLICATE_SAME_ACCESS))
            raw, thread, pid = _create_process(kernel, arguments, environment, cwd or manager.server_root, duplicates, desktop.name if desktop else None)
            process = ScriptProcess(raw, pid, arguments)
            process.stdin = parent_input
        if not kernel.AssignProcessToJobObject(job_handle, process._handle):
            raise ctypes.WinError(ctypes.get_last_error())
        identity = _handle_identity(kernel, int(process._handle))
        if identity[0] != pid or identity[2]:
            raise OSError("suspended launcher identity unavailable")
        owned = LaunchJob(job_handle, process, identity[1], manager.server_id,
                          manager.server_root.resolve(), manager.launch_script, tuple(arguments), desktop)
        manager._startup_launcher = process
        manager._owned_launch_job = owned
        if kernel.ResumeThread(thread) == 0xffffffff:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = True
        return process
    except Exception:
        # The newly created root has never executed, so it cannot have started
        # Minecraft. Clean up this suspended bootstrap only; never kill a live
        # server or retry the user's script when ownership setup fails.
        if process is not None and not resumed:
            _winapi.TerminateProcess(int(process._handle), 125)
            process.wait(5)
        if getattr(manager, "_owned_launch_job", None) is not None and manager._owned_launch_job.process is process:
            manager._owned_launch_job = None
        job_handle.Close()
        if parent_input:
            parent_input.close()
        if desktop:
            desktop.close()
        raise
    finally:
        if read_input and not read_input.closed:
            read_input.close()
        if thread is not None:
            _winapi.CloseHandle(thread)
        for handle in duplicates:
            _winapi.CloseHandle(handle)


def _owned(manager):
    owned = getattr(manager, "_owned_launch_job", None)
    if not isinstance(owned, LaunchJob):
        return None
    if (manager._startup_launcher is not owned.process or manager.server_id != owned.server_id
            or manager.server_root.resolve() != owned.root or manager.launch_script != owned.launcher
            or tuple(owned.process.args) != owned.arguments):
        raise OSError("original launcher ownership changed")
    pid, birth, _ = _handle_identity(_api(), int(owned.process._handle))
    if (pid, birth) != (owned.process.pid, owned.birth):
        raise OSError("original launcher handle/birth mismatch")
    return owned


def _pids(kernel, owned):
    capacity = 64
    while capacity <= 32768:
        class ProcessList(ctypes.Structure):
            _fields_ = [("assigned", w.DWORD), ("listed", w.DWORD), ("pids", ctypes.c_size_t * capacity)]
        value, used = ProcessList(), w.DWORD()
        ok = kernel.QueryInformationJobObject(owned.handle, 3, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(used))
        error = ctypes.get_last_error() if not ok else 0
        if ok and value.assigned <= capacity and value.listed == value.assigned:
            return [int(value.pids[i]) for i in range(value.listed)]
        if error not in (0, 234):  # ERROR_MORE_DATA
            raise ctypes.WinError(error)
        capacity = max(capacity * 2, int(value.assigned))
    raise OSError("launcher job process list exceeded bounds")


def _member(kernel, owned, pid):
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # vanished between enumeration and open
            return None
        raise OSError("launcher job member cannot be read")
    try:
        identity = _handle_identity(kernel, handle)
        member = w.BOOL()
        if not kernel.IsProcessInJob(handle, owned.handle, ctypes.byref(member)):
            raise OSError("launcher job membership unavailable")
        if identity[2] or not member.value:
            return None
        if identity[0] != pid or identity[1] < owned.birth:
            raise OSError("launcher job process identity mismatch")
        text, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)):
            raise OSError("launcher job member image unavailable")
        if _handle_identity(kernel, handle) != identity:
            return None
        return {"pid": pid, "birth": identity[1], "image": text.value}
    finally:
        kernel.CloseHandle(handle)


def snapshot(manager):
    owned = _owned(manager)
    if owned is None:
        return None
    kernel = _api()
    result = {"java_pid": 0, "launcher_pids": [], "watchdog_pids": [], "source": "windows_job"}
    from native_platforms import process_images
    runtimes = []
    for pid in _pids(kernel, owned):
        row = _member(kernel, owned, pid)
        if row is None:
            continue
        if Path(row["image"]).name.lower() in process_images(manager.platform):
            runtimes.append(pid)
        else:
            result["launcher_pids"].append(pid)
    if len(runtimes) == 1:
        result["java_pid"] = runtimes[0]
    else:
        # Multiple Java helpers are activity, not one arbitrarily chosen server.
        result["launcher_pids"].extend(runtimes)
    # A member may create another process while the first list is inspected.
    # An empty tree must be confirmed by the kernel again, not by vanished rows.
    if not result["java_pid"] and not result["launcher_pids"] and _pids(kernel, owned):
        raise OSError("launcher job changed while checking empty state")
    if _owned(manager) is not owned:
        raise OSError("launcher job changed during verification")
    return result


def process_matches(manager, pid):
    owned = _owned(manager)
    if owned is None or type(pid) is not int or pid <= 0:
        return False
    row = _member(_api(), owned, pid)
    from native_platforms import process_images
    return bool(row and Path(row["image"]).name.lower() in process_images(manager.platform)
                and _owned(manager) is owned)


def close_windows(manager):
    """Request ordinary WM_CLOSE on owned hidden windows; never click dialogs."""
    owned = _owned(manager)
    if owned is None or owned.desktop is None:
        return 0
    def matches(pid):
        return _member(_api(), owned, pid) is not None and _owned(manager) is owned
    return owned.desktop.request_close(matches)
