# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import base64
import ctypes
import csv
import gzip
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from collections import deque
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any, Callable
from native_platforms import profile as platform_profile, process_images, ready_line, stopping_line, uses_capture_log
CREATE_NO_WINDOW = 134217728
CREATE_NEW_CONSOLE = 16
PLAYER_NAME_RE = re.compile('^[A-Za-z0-9_]{1,16}$')
ITEM_ID_RE = re.compile('^[a-z0-9_.-]+:[a-z0-9_./-]+$')
JOIN_RE = re.compile('\\]: ([A-Za-z0-9_]{1,16}) joined the game$')
LEAVE_RE = re.compile('\\]: ([A-Za-z0-9_]{1,16}) left the game$')
LOG_CLOCK_RE = re.compile('^\\[(?P<clock>\\d{2}:\\d{2}:\\d{2})\\]')
LOG_LOCAL_DATETIME_RE = re.compile('^\\[(?P<day>\\d{1,2})(?P<month>\\d{1,2})月(?P<year>\\d{4}) (?P<clock>\\d{2}:\\d{2}:\\d{2})(?:\\.\\d+)?\\]')
LOG_CHINESE_DATETIME_RE = re.compile('^\\[(?P<day>\\d{1,2})(?P<month>十二|十一|[一二三四五六七八九十])月(?P<year>\\d{4}) (?P<clock>\\d{2}:\\d{2}:\\d{2})(?:\\.\\d+)?\\]')
CHINESE_MONTHS = {name: index for index, name in enumerate(('一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二'), start=1)}
LOG_ENGLISH_DATETIME_RE = re.compile('^\\[(?P<day>\\d{1,2})(?P<month>[A-Za-z]{3})(?P<year>\\d{4}) (?P<clock>\\d{2}:\\d{2}:\\d{2})(?:\\.\\d+)?\\]')
ENGLISH_MONTHS = {name: index for index, name in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), start=1)}
ARCHIVED_LOG_RE = re.compile('^(?P<date>\\d{4}-\\d{2}-\\d{2})-\\d+\\.log\\.gz$')
PLAYER_LIST_RE = re.compile('\\]: There are (?P<count>\\d+) of a max of \\d+ players online:(?: (?P<players>.*))?$')
SERVER_READY_RE = re.compile('\\]: Done \\([0-9.]+s\\)! For help, type \\"help\\"')
SERVER_STOPPING_RE = re.compile('\\]: Stopping server$')
BACKUP_MODES = {'light', 'full'}
LIGHT_BACKUP_EXCLUDED_NAMES = re.compile('^(?:DistantHorizons\\.sqlite(?:-wal|-shm)?|map_\\d+\\.dat|ae2_compass_.+\\.dat)$', re.IGNORECASE)

class PanelError(RuntimeError):
    pass

class StartupCancelled(PanelError):
    """A requested startup stop has finished, including supervisor children."""
STARTUP_OPERATION_NAMES = {'启动服务器', '重启服务器', '导入后启动服务器'}

def decode_server_log(data: bytes) -> str:
    """Read modern UTF-8 and legacy Chinese Windows Java logs without data loss.

    Java 8/17 can use the Windows default charset for Log4j files. In particular,
    Forge's numeric Chinese month contains GBK D4 C2, which must survive before
    the process-lifetime timestamp check. Never infer readiness from replacement
    characters or from a Done line whose timestamp cannot be parsed.
    """
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode('mbcs' if os.name == 'nt' else 'utf-8', errors='replace')

def atomic_write_text(path: Path, text: str, encoding: str='utf-8') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(text, encoding=encoding, newline='')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def atomic_write_json(path: Path, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    atomic_write_text(path, text, 'utf-8')

def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default

def validate_player_name(name: Any) -> str:
    name = str(name or '').strip()
    if not PLAYER_NAME_RE.fullmatch(name):
        raise PanelError('玩家名只能包含英文字母、数字和下划线，长度为 1～16。')
    return name

class ProcessMetrics:
    PROCESS_QUERY_LIMITED_INFORMATION = 4096
    PROCESS_VM_READ = 16
    FILETIME_EPOCH = 116444736000000000

    class FILETIME(ctypes.Structure):
        _fields_ = [('low', wintypes.DWORD), ('high', wintypes.DWORD)]

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]

    def __init__(self) -> None:
        self._samples: dict[int, tuple[float, float]] = {}
        self._cpu_count = max(1, os.cpu_count() or 1)
        self._kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self._psapi = ctypes.WinDLL('psapi', use_last_error=True)
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(self.FILETIME), ctypes.POINTER(self.FILETIME), ctypes.POINTER(self.FILETIME), ctypes.POINTER(self.FILETIME)]
        self._psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(self.PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD]

    @staticmethod
    def _filetime_value(value: 'ProcessMetrics.FILETIME') -> int:
        return value.high << 32 | value.low

    def get(self, pid: int) -> dict[str, Any]:
        if pid <= 0:
            return {'memory_mb': 0.0, 'cpu_percent': 0.0, 'uptime_seconds': 0}
        handle = self._kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION | self.PROCESS_VM_READ | 1048576, False, pid)
        if not handle:
            return {'memory_mb': 0.0, 'cpu_percent': 0.0, 'uptime_seconds': 0}
        try:
            if self._kernel32.WaitForSingleObject(handle, 0) != 258:
                self._samples.pop(pid, None)
                return {'memory_mb': 0.0, 'cpu_percent': 0.0, 'uptime_seconds': 0}
            created = self.FILETIME()
            exited = self.FILETIME()
            kernel = self.FILETIME()
            user = self.FILETIME()
            memory = self.PROCESS_MEMORY_COUNTERS_EX()
            memory.cb = ctypes.sizeof(memory)
            have_times = bool(self._kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)))
            have_memory = bool(self._psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb))
            now = time.time()
            cpu_percent = 0.0
            uptime = 0
            created_unix = None
            if have_times:
                process_time = (self._filetime_value(kernel) + self._filetime_value(user)) / 10000000
                previous = self._samples.get(pid)
                if previous:
                    process_delta = max(0.0, process_time - previous[0])
                    wall_delta = max(0.001, now - previous[1])
                    cpu_percent = min(100.0, process_delta / wall_delta / self._cpu_count * 100.0)
                self._samples[pid] = (process_time, now)
                created_unix = (self._filetime_value(created) - self.FILETIME_EPOCH) / 10000000
                uptime = max(0, int(now - created_unix))
            return {'memory_mb': round(memory.WorkingSetSize / (1024 * 1024), 1) if have_memory else 0.0, 'cpu_percent': round(cpu_percent, 1), 'uptime_seconds': uptime, 'created_at_unix': created_unix}
        finally:
            self._kernel32.CloseHandle(handle)

class WindowsPortTable:
    """Read current socket owners without spawning netstat on every monitor tick."""

    class TcpRow(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in ('state', 'local_address', 'local_port', 'remote_address', 'remote_port', 'pid')]

    class UdpRow(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in ('local_address', 'local_port', 'pid')]

    class Tcp6Row(ctypes.Structure):
        _fields_ = [('local_address', ctypes.c_ubyte * 16), ('local_scope', wintypes.DWORD), ('local_port', wintypes.DWORD), ('remote_address', ctypes.c_ubyte * 16), ('remote_scope', wintypes.DWORD), ('remote_port', wintypes.DWORD), ('state', wintypes.DWORD), ('pid', wintypes.DWORD)]

    class Udp6Row(ctypes.Structure):
        _fields_ = [('local_address', ctypes.c_ubyte * 16), ('local_scope', wintypes.DWORD), ('local_port', wintypes.DWORD), ('pid', wintypes.DWORD)]
    _api = None

    @classmethod
    def _read_rows(cls, protocol: str, family: int):
        if cls._api is None:
            api = ctypes.WinDLL('iphlpapi', use_last_error=True)
            for name in ('GetExtendedTcpTable', 'GetExtendedUdpTable'):
                function = getattr(api, name)
                function.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
                function.restype = wintypes.DWORD
            cls._api = api
        tcp = protocol == 'TCP'
        function = cls._api.GetExtendedTcpTable if tcp else cls._api.GetExtendedUdpTable
        table_class = 3 if tcp else 1
        row_type = (cls.TcpRow if tcp else cls.UdpRow) if family == socket.AF_INET else cls.Tcp6Row if tcp else cls.Udp6Row
        size = wintypes.DWORD(0)
        result = function(None, ctypes.byref(size), False, family, table_class, 0)
        if result not in (0, 122):
            raise OSError(result, 'Unable to size socket owner table')
        for _ in range(3):
            if size.value < 4 or size.value > 64 * 1024 * 1024:
                raise OSError('Invalid socket owner table size')
            buffer = ctypes.create_string_buffer(size.value)
            result = function(buffer, ctypes.byref(size), False, family, table_class, 0)
            if result == 122:
                continue
            if result:
                raise OSError(result, 'Unable to read socket owner table')
            count = wintypes.DWORD.from_buffer(buffer).value
            offset = ctypes.sizeof(wintypes.DWORD)
            if offset + count * ctypes.sizeof(row_type) > ctypes.sizeof(buffer):
                raise OSError('Truncated socket owner table')
            return (row_type * count).from_buffer_copy(buffer, offset)
        raise OSError('Socket owner table changed repeatedly')

    @classmethod
    def find_pid(cls, port: int, protocol: str) -> int:
        for family in (socket.AF_INET, socket.AF_INET6):
            for row in cls._read_rows(protocol, family):
                if socket.ntohs(row.local_port & 65535) == port and row.pid:
                    return int(row.pid)
        return 0

class ServerManager:
    DEFAULT_PANEL_CONFIG = {'poll_seconds': 2, 'backup_keep': 7, 'light_backup_keep': 3, 'backup_mode': 'full', 'gamerules': {'keepInventory': True, 'playersSleepingPercentage': 1}}
    EDITABLE_PROPERTIES: dict[str, tuple[str, Any, Any]] = {'motd': ('str', None, None), 'server-port': ('int', 1, 65535), 'server-ip': ('ip', None, None), 'gamemode': ('enum', {'survival', 'creative', 'adventure', 'spectator'}, None), 'difficulty': ('enum', {'peaceful', 'easy', 'normal', 'hard'}, None), 'max-players': ('int', 1, 200), 'view-distance': ('int', 2, 32), 'simulation-distance': ('int', 2, 32), 'spawn-protection': ('int', 0, 64), 'online-mode': ('bool', None, None), 'white-list': ('bool', None, None), 'enforce-whitelist': ('bool', None, None), 'pvp': ('bool', None, None), 'allow-flight': ('bool', None, None), 'enable-command-block': ('bool', None, None), 'op-permission-level': ('int', 1, 4)}

    def __init__(self, server_root: Path, panel_root: Path, *, server_id: str='default', data_root: Path | None=None, platform: str='neoforge', launch_script: str='qizhang-server-run-once.bat', control_script: str | None='qizhang-server-control.ps1', supports_watchdog: bool=True, voice_port: int=24454, runtime_policy=None) -> None:
        self.runtime_policy = runtime_policy
        self.server_root = server_root.resolve()
        self.panel_root = panel_root.resolve()
        self.server_id = str(server_id).strip() or 'default'
        self.platform = str(platform).strip().lower() or 'neoforge'
        self.data_root = data_root.resolve() if data_root is not None else self.panel_root / 'data'
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.launch_script = str(launch_script).strip()
        self.control_script = str(control_script).strip() if control_script else None
        self.supports_watchdog = False
        self.voice_port = max(1, min(65535, int(voice_port)))
        self.panel_config_path = self.data_root / 'panel-config.json'
        self.server_properties_path = self.server_root / 'server.properties'
        self.jvm_args_path = self.server_root / 'user_jvm_args.txt'
        if self.launch_script == 'qizhang-managed-start.bat':
            startup_config = read_json(self.server_root / 'qizhang-startup.json', {})
            if isinstance(startup_config, dict) and startup_config.get('jvm_file') == 'qizhang-startup.jvm-args.txt':
                self.jvm_args_path = self.server_root / 'qizhang-startup.jvm-args.txt'
        imported = read_json(self.server_root / 'qizhang-import.json', {})
        self.startup_adaptation_enabled = bool(isinstance(imported, dict) and isinstance(imported.get('startup_adaptation'), dict) and (imported['startup_adaptation'].get('enabled') is True))
        self.latest_log_path = self.server_root / 'logs' / ('panel-launcher.stdout.log' if uses_capture_log(self.platform) else 'latest.log')
        self.panel_log_path = self.data_root / 'panel.log'
        self.player_last_seen_path = self.data_root / 'player-last-seen.json'
        self.watchdog_pid_path = self.server_root / '.qizhang-watchdog.pid'
        self.stop_flag_path = self.server_root / '.qizhang-stop-autorestart.flag'
        self.maintenance_flag_path = self.server_root / '.qizhang-panel-maintenance.flag'
        self.starting_flag_path = self.server_root / '.qizhang-server-starting.flag'
        self.public_server_status_path = self.data_root / 'public-server-status.json'
        self.adopted_process_path = self.data_root / 'adopted-process.json'
        self.command_agent_root = self.server_root / 'qizhang-tools' / 'command-agent'
        self.light_backup_marker_path = self.server_root / '.qizhang-light-backup-save-off.json'
        self.java_path = self._resolve_java_path()
        self.python_path = Path(os.environ.get('PYTHON', os.sys.executable))
        self._config_lock = threading.RLock()
        self._panel_log_lock = threading.RLock()
        self._status_lock = threading.RLock()
        self._players_lock = threading.RLock()
        self._player_history_lock = threading.RLock()
        self._log_lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._mutation_lock = threading.RLock()
        self._shutdown_countdown_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._player_history_thread: threading.Thread | None = None
        self._metrics = ProcessMetrics()
        self._online_players: set[str] = set()
        self._log_position = 0
        self._log_identity: tuple[int, int] | None = None
        self._log_ready_seen = False
        self._log_graceful_stop_seen = False
        self._log_process_identity: tuple[int, float] | None = None
        self._log_process_started_at: datetime | None = None
        self._status_transition_initialized = False
        self._last_observed_server_pid = 0
        self._last_notified_online = False
        self._absence_polls = 0
        self._last_exit_kind = 'unknown'
        self._last_exit_at: str | None = None
        self._planned_shutdown_until = 0.0
        self._last_state_change_at = datetime.now().isoformat(timespec='seconds')
        self._last_public_status_write = 0.0
        self._last_public_state = 'unknown'
        self._recent_log_lines: deque[str] = deque(maxlen=2000)
        self._status: dict[str, Any] = {}
        self._operation: dict[str, Any] = {'active': False, 'name': '', 'message': '', 'started_at': None, 'finished_at': None, 'ok': True, 'progress': None}
        self._last_startup_operation: dict[str, Any] = {}
        self._startup_cancel_requested = threading.Event()
        self._startup_stop_owned = None
        self._startup_stop_attempted = False
        self._startup_waiting = False
        self._startup_log_baseline: dict[Path, tuple[Any, ...] | None] = {}
        self._startup_launcher: subprocess.Popen | None = None
        self._owned_direct_launch = None
        self._owned_script_launch = None
        self._owned_launch_job = None
        self._console_pipe_lock = threading.Lock()
        self._console_pipe_pending = None
        self.native_watchdog = None
        self._startup_probe_lock = threading.Lock()
        self._startup_probe_at = 0.0
        self._startup_probe_result: dict[str, Any] | None = None
        self._startup_notices: deque[str] = deque(maxlen=10)
        self._shutdown_countdown_cancel: threading.Event | None = None
        self._shutdown_countdown_thread: threading.Thread | None = None
        self._shutdown_countdown: dict[str, Any] = {'active': False, 'phase': 'idle', 'requested_seconds': 0, 'remaining_seconds': 0, 'started_at': None, 'ends_at': None, 'can_cancel': False, 'message': '没有正在进行的停服倒计时。'}
        self.config = self._load_panel_config()

    def _resolve_java_path(self) -> Path:
        candidates: list[Path] = []
        configured_path = self.server_root / 'qizhang-java-path.txt'
        try:
            configured_java = configured_path.read_text(encoding='utf-8-sig').strip()
        except OSError:
            configured_java = ''
        if configured_java:
            configured = Path(configured_java)
            candidates.append(configured if configured.is_absolute() else self.server_root / configured)
        imported = read_json(self.server_root / 'qizhang-import.json', {})
        if isinstance(imported, dict):
            selected_java = imported.get('java_relative_path') or imported.get('java_path')
            if isinstance(selected_java, str) and selected_java:
                selected = Path(selected_java)
                candidates.append(selected if selected.is_absolute() else self.server_root / selected)
        candidates.append(self.server_root / 'runtime' / 'bin' / 'java.exe')
        candidates.append(self.server_root / 'runtime' / 'java8' / 'bin' / 'java.exe')
        java_home = os.environ.get('JAVA_HOME')
        if java_home:
            candidates.append(Path(java_home) / 'bin' / 'java.exe')
        path_java = shutil.which('java.exe')
        if path_java:
            candidates.append(Path(path_java))
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
        return Path('java.exe')

    def _load_panel_config(self) -> dict[str, Any]:
        value = read_json(self.panel_config_path, {})
        merged = json.loads(json.dumps(self.DEFAULT_PANEL_CONFIG))
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'gamerules' and isinstance(item, dict):
                    merged['gamerules'].update(item)
                elif key in merged:
                    merged[key] = item
        if getattr(self, 'runtime_policy', None) is None or False or (not self.panel_config_path.exists()):
            atomic_write_json(self.panel_config_path, merged)
        return merged

    def watchdog_enabled(self):
        return False

    def save_panel_config(self) -> None:
        with self._config_lock:
            atomic_write_json(self.panel_config_path, self.config)

    def log(self, message: str, level: str='INFO') -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f'{timestamp} [{level}] {message}\n'
        with self._panel_log_lock:
            self.panel_log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if self.panel_log_path.exists() and self.panel_log_path.stat().st_size > 5 * 1024 * 1024:
                    rotated = self.panel_log_path.with_name('panel.previous.log')
                    rotated.unlink(missing_ok=True)
                    os.replace(self.panel_log_path, rotated)
            except OSError:
                pass
            with self.panel_log_path.open('a', encoding='utf-8') as handle:
                handle.write(line)

    @staticmethod
    def _logout_timestamp_from_line(line: str, log_date: str) -> str | None:
        local = LOG_LOCAL_DATETIME_RE.search(line) or LOG_CHINESE_DATETIME_RE.search(line)
        if local:
            try:
                value = datetime(int(local.group('year')), int(local.group('month')) if local.group('month').isdigit() else CHINESE_MONTHS[local.group('month')], int(local.group('day')), *map(int, local.group('clock').split(':')))
            except ValueError:
                return None
            return value.isoformat(timespec='seconds')
        english = LOG_ENGLISH_DATETIME_RE.search(line)
        if english:
            month = ENGLISH_MONTHS.get(english.group('month').lower())
            if not month:
                return None
            try:
                value = datetime(int(english.group('year')), month, int(english.group('day')), *map(int, english.group('clock').split(':')))
            except ValueError:
                return None
            return value.isoformat(timespec='seconds')
        match = LOG_CLOCK_RE.search(line)
        if not match:
            return None
        timestamp = f'{log_date}T{match.group('clock')}'
        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        return timestamp

    def _archived_log_files(self):
        """Find rotated logs needed to reconstruct this running process's output."""
        result = []
        try:
            paths = list((self.server_root / 'logs').glob('*.log.gz'))
        except OSError:
            return result
        for path in paths:
            match = ARCHIVED_LOG_RE.fullmatch(path.name)
            if match:
                result.append((path, match.group('date')))
        return sorted(result, key=lambda item: (item[1], item[0].name))

    def start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name='QiZhang-Panel-Monitor', daemon=True)
        self._monitor_thread.start()

    def stop_monitor(self) -> None:
        self._stop_event.set()
        with self._shutdown_countdown_lock:
            countdown_cancel = self._shutdown_countdown_cancel
            countdown_thread = self._shutdown_countdown_thread
        if countdown_cancel is not None:
            countdown_cancel.set()
        if countdown_thread and countdown_thread is not threading.current_thread():
            countdown_thread.join(timeout=5)
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
        if self._player_history_thread:
            self._player_history_thread.join(timeout=3)

    @staticmethod
    def process_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(4096 | 1048576, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel32.CloseHandle(handle)

    @staticmethod
    def process_image_name(pid: int) -> str:
        if pid <= 0:
            return ''
        PROCESS_QUERY_LIMITED_INFORMATION = 4096
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ''
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ''
            return buffer.value
        finally:
            kernel32.CloseHandle(handle)

    def _is_server_java_pid(self, pid: int) -> bool:
        image = Path(self.process_image_name(pid)).name.lower()
        return image in process_images(self.platform)

    def platform_profile(self) -> dict[str, Any]:
        return platform_profile(getattr(self, 'platform', 'vanilla'), getattr(self, 'server_root', None))

    def _require_platform_capability(self, capability: str) -> None:
        if not self.platform_profile()['capabilities'].get(capability, False):
            raise PanelError('当前平台不支持此游戏服专用操作；可使用原始控制台执行该平台命令。')

    def _runtime_endpoint(self) -> tuple[int, str]:
        spec = self.platform_profile()
        values = self.get_server_properties()
        return (int(values.get('server-port') or spec['default_port']), spec['network_protocol'])

    def _platform_editable_properties(self):
        allowed = self.platform_profile().get('editable_properties')
        if allowed is None:
            return list(self.EDITABLE_PROPERTIES)
        allowed = list(allowed)
        return allowed

    def _owned_runtime_pid(self) -> int:
        from native_managed_launch import owned_process_pid
        return owned_process_pid(self)

    def _find_port_pid(self, port: int, protocol: str='TCP') -> int:
        protocol = protocol.upper()
        if os.name == 'nt' and protocol in {'TCP', 'UDP'}:
            try:
                return WindowsPortTable.find_pid(int(port), protocol)
            except (OSError, AttributeError, ValueError):
                pass
        try:
            output = subprocess.run(['netstat', '-ano', '-p', protocol.upper()], capture_output=True, text=True, encoding='mbcs', errors='replace', timeout=4, creationflags=CREATE_NO_WINDOW, check=False).stdout
        except (OSError, subprocess.TimeoutExpired):
            return 0
        wanted = str(port)
        for raw in output.splitlines():
            parts = raw.split()
            if not parts or parts[0].upper() != protocol.upper():
                continue
            if protocol.upper() == 'TCP':
                if len(parts) < 5 or parts[-2].upper() != 'LISTENING':
                    continue
                local, pid_text = (parts[1], parts[-1])
            else:
                if len(parts) < 4:
                    continue
                local, pid_text = (parts[1], parts[-1])
            if local.rsplit(':', 1)[-1] == wanted and pid_text.isdigit():
                return int(pid_text)
        return 0

    def _process_command_line(self, pid: int) -> str:
        try:
            result = subprocess.run(['C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', '-NoProfile', '-Command', f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"], capture_output=True, text=True, encoding='mbcs', errors='replace', timeout=8, creationflags=CREATE_NO_WINDOW, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return ''
        return result.stdout.strip() if result.returncode == 0 else ''

    def _process_parent_pid(self, pid: int) -> int:
        try:
            result = subprocess.run(['C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', '-NoProfile', '-Command', f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').ParentProcessId"], capture_output=True, text=True, encoding='mbcs', errors='replace', timeout=8, creationflags=CREATE_NO_WINDOW, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return 0
        value = result.stdout.strip() if result.returncode == 0 else ''
        return int(value) if value.isdigit() else 0

    def _process_creation_time(self, pid: int) -> str:
        try:
            result = subprocess.run(['C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', '-NoProfile', '-Command', f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; if ($p) {{ $p.CreationDate.ToUniversalTime().ToString('o') }}"], capture_output=True, text=True, encoding='mbcs', errors='replace', timeout=8, creationflags=CREATE_NO_WINDOW, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return ''
        return result.stdout.strip() if result.returncode == 0 else ''

    def _adopted_server_command_matches(self, pid: int, image: str, command_line: str) -> bool:
        identity = read_json(self.adopted_process_path, {})
        if not isinstance(identity, dict):
            return False
        try:
            expected_pid = int(identity.get('pid', 0))
        except (TypeError, ValueError):
            return False
        if expected_pid != pid or identity.get('server_id') != self.server_id:
            return False
        recorded_creation = str(identity.get('creation_time_utc', ''))
        actual_creation = self._process_creation_time(pid)
        if not recorded_creation or not hmac.compare_digest(recorded_creation, actual_creation):
            return False
        recorded_image = str(identity.get('image_path', '')).lower()
        actual_image = str(Path(image).resolve()).lower()
        if not recorded_image or not hmac.compare_digest(recorded_image, actual_image):
            return False
        recorded_hash = str(identity.get('command_sha256', '')).lower()
        actual_hash = hashlib.sha256(command_line.encode('utf-8')).hexdigest()
        return len(recorded_hash) == 64 and hmac.compare_digest(recorded_hash, actual_hash)

    def _watchdog_command_matches(self, pid: int) -> bool:
        command_line = self._process_command_line(pid).lower()
        expected = (str(self.server_root / 'qizhang-server-watchdog.ps1').lower(), str(self.server_root / 'qizhang-server-watchdog.py').lower())
        return bool(command_line) and any((marker in command_line for marker in expected))

    def _server_command_matches(self, pid: int) -> bool:
        try:
            if self._owned_runtime_pid() == pid:
                return True
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        from native_launch_job import process_matches
        try:
            if process_matches(self, pid):
                return True
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        image = self.process_image_name(pid)
        if not image:
            return False
        if self.platform_profile()['runtime'] in {'native', 'php'}:
            from native_platform_launch import read
            try:
                cfg = read(self.server_root, platform=self.platform, server_id=self.server_id)
                if Path(image).resolve() != Path(cfg['runtime_path']).resolve():
                    return False
                if cfg['kind'] == 'native':
                    return True
                command = self._process_command_line(pid).replace('/', '\\').lower()
                entry = str((self.server_root / cfg['entry']).resolve()).replace('/', '\\').lower()
                return bool(re.search('(?:^|[\\s"])' + re.escape(entry) + '(?=$|[\\s"])', command))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                return False
        if self.java_path.is_file():
            try:
                if Path(image).resolve() != self.java_path.resolve():
                    return False
            except OSError:
                return False
        from native_script_identity import script_child_matches
        try:
            if script_child_matches(self, pid):
                return True
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        command_line = self._process_command_line(pid).lower().replace('\\', '/')
        panel_marker = f'-dqizhang.panel.server_id={self.server_id.lower()}'
        if panel_marker in command_line:
            return True
        if self._adopted_server_command_matches(pid, image, command_line):
            return True
        if self._uses_file_control():
            try:
                self._read_file_control_status(pid, verify_process=True)
                return True
            except PanelError:
                return False
        library_marker = {'neoforge': '@libraries/net/neoforged/neoforge/', 'forge': '@libraries/net/minecraftforge/forge/'}.get(self.platform)
        markers_match = bool(library_marker) and all((marker in command_line for marker in ('@user_jvm_args.txt', library_marker, '/win_args.txt')))
        if not markers_match:
            return False
        parent_pid = self._process_parent_pid(pid)
        parent_command = self._process_command_line(parent_pid).lower()
        expected_launcher = str(self.server_root / self.launch_script).lower()
        return bool(parent_command) and expected_launcher in parent_command

    def _read_watchdog_pid(self, validate_command: bool=False) -> int:
        try:
            value = int(self.watchdog_pid_path.read_text(encoding='ascii').strip())
        except (OSError, ValueError):
            return 0
        image = Path(self.process_image_name(value)).name.lower()
        if image not in {'powershell.exe', 'pwsh.exe', 'python.exe', 'pythonw.exe'}:
            return 0
        if validate_command and (not self._watchdog_command_matches(value)):
            return 0
        return value

    @staticmethod
    def _property_records(text: str) -> list[tuple[str, str]]:
        """Pair logical property lines with original physical bytes-as-text.

        Java Properties.load: an odd trailing backslash continues a property;
        comment lines never continue. Keep raw records for partial replacement.
        """
        lines = re.findall('[^\\r\\n]*(?:\\r\\n|\\r|\\n|$)', text)
        records = []
        index = 0
        while index < len(lines):
            raw = lines[index]
            index += 1
            if not raw:
                continue
            logical = raw.rstrip('\r\n')
            if not logical.lstrip(' \t\x0c').startswith(('#', '!')):
                while (len(logical) - len(logical.rstrip('\\'))) % 2 and index < len(lines) and lines[index]:
                    continuation = lines[index]
                    index += 1
                    raw += continuation
                    logical = logical[:-1] + continuation.rstrip('\r\n').lstrip(' \t\x0c')
            records.append((logical, raw))
        return records

    def get_server_properties(self) -> dict[str, str]:
        if self.platform_profile()['family'] == 'proxy':
            from native_platform_config import read_endpoint
            return read_endpoint(self.server_root, self.platform)
        result: dict[str, str] = {}
        try:
            text = self.server_properties_path.read_text(encoding='utf-8-sig')
        except OSError:
            return result
        for line, _ in self._property_records(text):
            if not line or line.lstrip().startswith(('#', '!')) or '=' not in line:
                continue
            key, value = line.split('=', 1)
            result[key.strip()] = value.strip()
        return result

    def _monitor_loop(self) -> None:
        self._initialize_log_state()
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                properties = self.get_server_properties()
                server_port, network_protocol = self._runtime_endpoint()
                candidate_pid = self._find_port_pid(server_port, network_protocol)
                server_pid = candidate_pid if self._is_server_java_pid(candidate_pid) else 0
                if server_pid and (not self._server_command_matches(server_pid)):
                    raise PanelError('监听端口的进程身份与本实例不一致。')
                if not server_pid:
                    server_pid = self._owned_runtime_pid()
                if not candidate_pid and self.starting_flag_path.exists():
                    activity = self._startup_process_snapshot()
                    if activity is not None:
                        server_pid = activity['java_pid']
                        if not server_pid and (not activity['launcher_pids']) and (not activity['watchdog_pids']):
                            self.reconcile_startup_state()
                metrics = self._metrics.get(server_pid)
                self._sync_log_process(server_pid, metrics.get('created_at_unix'))
                self._consume_new_log_lines()
                fully_started = bool(server_pid and candidate_pid == server_pid and self._log_ready_seen and (not self._log_graceful_stop_seen))
                if fully_started and self.starting_flag_path.exists():
                    self.starting_flag_path.unlink(missing_ok=True)
                voice_port = self.voice_port
                voice_pid = self._find_port_pid(voice_port, 'UDP')
                watchdog_pid = self._read_watchdog_pid()
                with self._players_lock:
                    players = sorted(self._online_players, key=str.lower)
                status = {'running': bool(server_pid), 'ready': fully_started, 'starting': bool((self.starting_flag_path.exists() or server_pid) and (not fully_started) and (not self._log_graceful_stop_seen)), 'pid': server_pid, 'cpu_percent': metrics['cpu_percent'], 'memory_mb': metrics['memory_mb'], 'uptime_seconds': metrics['uptime_seconds'], 'port': server_port, 'network_protocol': network_protocol, 'voice_port': voice_port, 'voice_running': bool(voice_pid), 'watchdog_running': bool(watchdog_pid), 'watchdog_pid': watchdog_pid, 'online_players': players, 'online_count': len(players), 'max_players': int(properties.get('max-players', '20') or 20), 'difficulty': properties.get('difficulty', 'hard'), 'motd': properties.get('motd', ''), 'updated_at': datetime.now().isoformat(timespec='seconds')}
                with self._status_lock:
                    self._status = status
                self._handle_server_state_transition(server_pid, fully_started)
            except Exception as error:
                with self._status_lock:
                    self._status['monitor_error'] = str(error)
                self.log(f'状态监控失败：{error}', 'ERROR')
            delay = max(0.5, float(self.config.get('poll_seconds', 2)) - (time.monotonic() - started))
            self._stop_event.wait(delay)

    def _initialize_log_state(self) -> None:
        with self._players_lock:
            self._online_players.clear()
        self._log_position = 0
        self._log_identity = None
        self._log_ready_seen = False
        self._log_graceful_stop_seen = False
        self._log_process_identity = None
        self._log_process_started_at = None

    def _sync_log_process(self, pid: int, created_at: float | None) -> None:
        if not pid or created_at is None:
            return
        identity = (pid, created_at)
        if identity == self._log_process_identity:
            return
        self._initialize_log_state()
        self._log_process_identity = identity
        self._log_process_started_at = datetime.fromtimestamp(created_at).replace(microsecond=0)
        self._restore_current_process_logs(created_at)

    def _restore_current_process_logs(self, created_at: float) -> None:
        archives = []
        for path, log_date in self._archived_log_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime >= created_at:
                archives.append((stat.st_mtime_ns, path, log_date))
        updates: dict[str, str] = {}
        for _, path, log_date in sorted(archives):
            try:
                with gzip.open(path, 'rb') as handle:
                    for raw in handle:
                        self._apply_server_log_line(decode_server_log(raw).rstrip('\r\n'), log_date, updates)
            except (OSError, EOFError) as error:
                self.log(f'恢复当前进程日志失败 {path.name}：{error}', 'WARN')
        if updates:
            pass

    def _apply_server_log_line(self, line: str, log_date: str, logout_updates: dict[str, str]) -> None:
        line = re.sub('\\x1b\\[[0-9;]*[A-Za-z]', '', line)
        timestamp = self._logout_timestamp_from_line(line, log_date)
        if uses_capture_log(getattr(self, 'platform', 'vanilla')):
            if not getattr(self, '_owned_direct_launch', None) or self._log_process_started_at is None:
                return
            if not timestamp:
                timestamp = self._log_process_started_at.isoformat()
        if self._log_process_started_at is None or not timestamp or datetime.fromisoformat(timestamp) < self._log_process_started_at:
            return
        if ready_line(getattr(self, 'platform', 'vanilla'), line):
            self._log_ready_seen = True
            self._log_graceful_stop_seen = False
        elif stopping_line(getattr(self, 'platform', 'vanilla'), line):
            self._log_graceful_stop_seen = True
        joined = JOIN_RE.search(line)
        if joined:
            with self._players_lock:
                self._online_players.add(joined.group(1))
            return
        left = LEAVE_RE.search(line)
        if left:
            name = left.group(1)
            with self._players_lock:
                self._online_players.discard(name)
            if timestamp > logout_updates.get(name, ''):
                logout_updates[name] = timestamp
            return
        player_list = PLAYER_LIST_RE.search(line)
        if player_list:
            expected_count = int(player_list.group('count'))
            raw_players = player_list.group('players') or ''
            listed_players = {name.strip() for name in raw_players.split(',') if PLAYER_NAME_RE.fullmatch(name.strip())}
            if expected_count == 0 or len(listed_players) == expected_count:
                with self._players_lock:
                    self._online_players = listed_players

    def _consume_new_log_lines(self) -> None:
        try:
            stat = self.latest_log_path.stat()
        except OSError:
            return
        if uses_capture_log(getattr(self, 'platform', 'vanilla')) and (self._log_process_started_at is None or stat.st_mtime < self._log_process_started_at.timestamp()):
            return
        log_date = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d')
        logout_updates: dict[str, str] = {}
        identity = (stat.st_dev, stat.st_ino)
        if self._log_identity != identity or stat.st_size < self._log_position:
            self._log_identity = identity
            self._log_position = 0
            with self._log_lock:
                self._recent_log_lines.clear()
        with self.latest_log_path.open('rb') as handle:
            handle.seek(self._log_position)
            for raw in handle:
                if not raw.endswith(b'\n'):
                    break
                line = decode_server_log(raw).rstrip('\r\n')
                with self._log_lock:
                    self._recent_log_lines.append(line)
                self._apply_server_log_line(line, log_date, logout_updates)
                self._log_position = handle.tell()
        if logout_updates:
            pass

    def _handle_server_state_transition(self, server_pid: int, fully_started: bool) -> None:
        if not self._status_transition_initialized:
            self._status_transition_initialized = True
            self._last_observed_server_pid = server_pid
            self._last_notified_online = bool(server_pid and self._log_ready_seen)
            return
        previous_pid = self._last_observed_server_pid
        now = datetime.now().isoformat(timespec='seconds')
        if previous_pid and server_pid != previous_pid:
            if not server_pid:
                self._absence_polls += 1
                if self._absence_polls < 3:
                    return
            else:
                self._absence_polls = 0
            clean_stop = bool(self._log_graceful_stop_seen or self.maintenance_flag_path.exists() or self.stop_flag_path.exists() or (time.monotonic() <= self._planned_shutdown_until))
            self._last_exit_kind = 'clean' if clean_stop else 'crash'
            self._last_exit_at = now
            self._last_state_change_at = now
            with self._players_lock:
                disconnected_players = sorted(self._online_players)
                self._online_players.clear()
            if disconnected_players:
                pass
            if self._last_notified_online:
                self._last_notified_online = False
            self._planned_shutdown_until = 0.0
        elif fully_started and (not self._last_notified_online):
            self._last_state_change_at = now
            self._last_notified_online = True
        if server_pid:
            self._absence_polls = 0
        self._last_observed_server_pid = server_pid

    def get_status(self) -> dict[str, Any]:
        with self._status_lock:
            status = json.loads(json.dumps(self._status))
        with self._operation_lock:
            operation = json.loads(json.dumps(self._operation))
            startup = json.loads(json.dumps(self._last_startup_operation))
            waiting = self._startup_waiting
        active_startup = bool(operation.get('active') and operation.get('name') in STARTUP_OPERATION_NAMES)
        if active_startup:
            status['starting'] = True
            status['ready'] = False
        status['startup_failed'] = bool(not active_startup and startup.get('finished_at') and (startup.get('ok') is False) and (not startup.get('cancelled')) and (not status.get('ready')))
        status['startup_error'] = str(startup.get('message', '')) if status['startup_failed'] else ''
        status['startup_operation_id'] = str(startup.get('id', ''))
        status['startup_adaptation_enabled'] = bool(getattr(self, 'startup_adaptation_enabled', False))
        status['managed_startup'] = self.launch_script in {'qizhang-managed-start.bat', 'qizhang-platform-start.bat'}
        status['startup_recovery_supported'] = bool(self.launch_script == 'qizhang-managed-start.bat' and status['startup_adaptation_enabled'])
        status['platform_profile'] = self.platform_profile()
        status['capabilities'] = self.platform_profile()['capabilities']
        status['can_stop_starting'] = bool(active_startup and waiting and self._supports_startup_stop() or (not operation.get('active') and (not status.get('ready')) and self.starting_flag_path.exists() and (self._owned_startup_stop_target() is not None)))
        status['startup_stop_requested'] = bool(active_startup and self._startup_cancel_requested.is_set())
        age = None
        try:
            sampled = datetime.fromisoformat(str(status.get('updated_at', '')))
            age = max(0.0, (datetime.now(sampled.tzinfo) - sampled).total_seconds())
        except (TypeError, ValueError):
            pass
        stale = age is None or age > max(15.0, float(self.config.get('poll_seconds', 2)) * 3)
        known = not stale and (not status.get('monitor_error'))
        if not known:
            state = 'unknown'
        elif active_startup:
            state = 'starting'
        elif status.get('running') and self._log_graceful_stop_seen:
            state = 'stopping'
        elif status.get('ready'):
            state = 'online'
        elif status.get('starting') or status.get('running'):
            state = 'starting'
        elif self.maintenance_flag_path.exists():
            state = 'maintenance'
        elif status.get('startup_failed'):
            state = 'startup_failed'
        elif self._last_exit_kind == 'crash' and (not self._log_graceful_stop_seen):
            state = 'crashed'
        else:
            state = 'offline'
        status.update(state=state, status_known=bool(known), status_stale=stale, sample_age_seconds=round(age, 1) if age is not None else None, monitor_error=str(status.get('monitor_error', '')))
        with self._shutdown_countdown_lock:
            shutdown_countdown = json.loads(json.dumps(self._shutdown_countdown))
        return {'server': status, 'platform_profile': self.platform_profile(), 'operation': operation, 'shutdown_countdown': shutdown_countdown}

    def get_logs(self, lines: int=200, query: str='', level: str='') -> list[str]:
        lines = max(20, min(1000, int(lines)))
        with self._log_lock:
            recent = list(self._recent_log_lines)
        blocks: list[tuple[int, list[str]]] = []

        def add_block(path: Path, output: list[str]) -> None:
            if not output:
                return
            try:
                changed = path.stat().st_mtime_ns
            except OSError:
                changed = 0
            blocks.append((changed, output))
        add_block(self.latest_log_path, recent)
        startup_output = self._startup_waiting or self.starting_flag_path.exists() or (self._last_startup_operation.get('ok') is False and (not self._status.get('ready')))
        if not recent or startup_output:
            add_block(self.server_root / 'logs/panel-launcher.stdout.log', self._launcher_log_lines('stdout', 'INFO', lines if not recent else min(lines, 100)))
        add_block(self.server_root / 'logs/panel-launcher.stderr.log', self._launcher_log_lines('stderr', 'ERROR', min(lines, 100)))
        source = [line for _, output in sorted(blocks, key=lambda block: block[0]) for line in output]
        source.extend(self._startup_notices)
        query_lower = query.strip().lower()
        level_upper = level.strip().upper()
        filtered: list[str] = []
        for line in source:
            if query_lower and query_lower not in line.lower():
                continue
            if level_upper and f'/{level_upper}]' not in line.upper():
                continue
            filtered.append(line)
        return filtered[-lines:]

    def _launcher_log_lines(self, channel: str, level: str, lines: int) -> list[str]:
        path = self.server_root / 'logs' / f'panel-launcher.{channel}.log'
        try:
            with path.open('rb') as handle:
                handle.seek(max(0, path.stat().st_size - 65536))
                data = handle.read(65536)
            text = '\n'.join((decode_server_log(line) for line in data.splitlines()))
        except OSError:
            return []
        result: list[str] = []
        current_level = level
        for line in text.splitlines():
            if not line.strip():
                continue
            explicit = re.search('/(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\\]', line, re.IGNORECASE)
            if not explicit:
                explicit = re.match('^(?:\\d{4}-\\d{2}-\\d{2}T\\S+\\s+\\S+\\s+)?(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)(?=[\\s:\\]])', line.lstrip(), re.IGNORECASE)
            if explicit:
                current_level = explicit.group(1).upper()
                if current_level == 'WARNING':
                    current_level = 'WARN'
            elif channel == 'stderr' and re.match('^(?:Exception in thread\\b|Unrecognized (?:option|VM option)\\b|Could not (?:create|find or load)\\b)', line.lstrip(), re.IGNORECASE):
                current_level = 'ERROR'
            result.append(f'[启动器/{current_level}] {line}')
        return result[-lines:]

    def server_pid(self) -> int:
        port, protocol = self._runtime_endpoint()
        pid = self._find_port_pid(port, protocol)
        return pid if self._is_server_java_pid(pid) else self._owned_runtime_pid()

    def validated_server_pid(self, *, strict: bool=False) -> int:
        port, protocol = self._runtime_endpoint()
        if strict:
            if os.name != 'nt' or protocol.upper() not in {'TCP', 'UDP'}:
                raise PanelError('无法严格核验服务器监听端口，面板暂不退出。')
            pid = WindowsPortTable.find_pid(int(port), protocol.upper())
        else:
            pid = self._find_port_pid(port, protocol)
        if not pid:
            return self._owned_runtime_pid()
        if not self._is_server_java_pid(pid) or not self._server_command_matches(pid):
            raise PanelError(f'{port} 端口被无法确认身份的进程 PID={pid} 占用；为避免误操作，面板已拒绝附加、停止或备份。')
        return pid

    def send_command(self, command: str) -> None:
        command = str(command or '').strip()
        if command.startswith('/'):
            command = command[1:].lstrip()
        if not command or len(command) > 2000 or '\n' in command or ('\r' in command) or ('\x00' in command):
            raise PanelError('命令为空、过长或包含非法换行。')
        pid = self.validated_server_pid()
        if not pid:
            raise PanelError('服务器当前未运行，无法执行命令。')
        if self._uses_file_control():
            self._send_file_control_command(pid, command)
            from native_diagnostics import record_submission
            record_submission(self, pid, 'file-control')
            self.log(f'执行服务端命令：{command}')
            return
        from native_console_pipe import send_command as send_console_command, ConsolePipeError
        try:
            submitted = send_console_command(self, pid, command)
        except ConsolePipeError as error:
            raise PanelError(str(error)) from error
        if submitted:
            from native_diagnostics import record_submission
            record_submission(self, pid, 'stdin')
            self.log(f'已提交服务端标准输入命令：{command}')
            return
        if self.platform_profile()['family'] != 'java':
            raise PanelError('此平台的命令需要本面板直接启动后保留的标准输入通道；请正常停服后从面板启动。未尝试 Java 附加或重复发送。')
        from native_rcon import send_command as send_rcon_command, RconError
        try:
            receipt = send_rcon_command(self, pid, command)
        except RconError as error:
            raise PanelError(str(error)) from error
        if receipt is not None:
            from native_diagnostics import record_submission
            record_submission(self, pid, 'rcon')
            self.log(f'已提交服务端命令：{command}')
            return
        from native_command_bridge import send_command as send_builtin_command, CommandBridgeError
        try:
            send_builtin_command(self, pid, command)
        except CommandBridgeError as error:
            raise PanelError(str(error)) from error
        from native_diagnostics import record_submission
        record_submission(self, pid, 'java-bridge')
        self.log(f'已提交服务端命令：{command}')
        return

    def _uses_file_control(self) -> bool:
        status = self.server_root / 'qizhang-control' / 'status.json'
        if status.exists() or status.is_symlink():
            return True
        metadata = read_json(self.server_root / 'qizhang-import.json', {})
        return isinstance(metadata, dict) and metadata.get('command_channel') == 'serverfoundation-file-v1'

    def _checked_control_path(self, relative: str) -> Path:
        target = self.server_root / 'qizhang-control' / relative
        root = self.server_root.resolve()
        for candidate in (target, *target.parents):
            if candidate == root:
                break
            if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
                raise PanelError('本地命令通道包含链接或目录联接，已拒绝操作。')
        if not target.resolve().is_relative_to(root):
            raise PanelError('本地命令通道路径越界，已拒绝操作。')
        return target

    def _read_control_json(self, relative: str) -> dict[str, Any]:
        path = self._checked_control_path(relative)
        try:
            with path.open('rb') as handle:
                data = handle.read(16385)
            if len(data) > 16384:
                raise ValueError('record too large')
            record = json.loads(data.decode('utf-8-sig'))
            if not isinstance(record, dict):
                raise ValueError('record is not an object')
            return record
        except (OSError, UnicodeError, ValueError) as error:
            raise PanelError('本地命令通道尚未就绪或记录无效，请检查 ServerFoundation 插件启动日志。') from error

    def _read_file_control_status(self, pid: int, *, verify_process: bool=False) -> dict[str, Any]:
        status = self._read_control_json('status.json')
        try:
            if status.get('protocol') != 1 or type(status.get('pid')) is not int or status['pid'] != pid or (type(status.get('start_time')) is not int) or (status['start_time'] <= 0) or (not isinstance(status.get('instance_root'), str)):
                raise ValueError('protocol or process identity mismatch')
            recorded_root = Path(status['instance_root'])
            if not recorded_root.is_absolute() or recorded_root.resolve() != self.server_root.resolve():
                raise ValueError('server root mismatch')
            if verify_process:
                created = self._process_creation_time(pid)
                if not created:
                    raise ValueError('process creation time unavailable')
                process_time = datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp() * 1000
                if abs(process_time - status['start_time']) > 1500:
                    raise ValueError('stale process lifetime')
            return status
        except (OSError, TypeError, ValueError) as error:
            raise PanelError('本地命令通道与当前服务器进程不匹配，已拒绝执行命令。') from error

    def _send_file_control_command(self, pid: int, command: str) -> None:
        status = self._read_file_control_status(pid, verify_process=True)
        identifier = uuid.uuid4().hex
        request_relative = f'requests/{identifier}.json'
        response_relative = f'responses/{identifier}.json'
        request = self._checked_control_path(request_relative)
        response = self._checked_control_path(response_relative)
        pending = self._checked_control_path(f'requests/{identifier}.tmp')
        if not request.parent.is_dir() or not response.parent.is_dir():
            raise PanelError('本地命令通道尚未就绪，请等待 ServerFoundation 完成启动。')
        expires_at = int(time.time() * 1000) + 15000
        payload = {'protocol': 1, 'id': identifier, 'pid': pid, 'start_time': status['start_time'], 'expires_at': expires_at, 'command': command}
        try:
            with pending.open('x', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            self._checked_control_path(request_relative)
            os.replace(pending, request)
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                self._checked_control_path(response_relative)
                if response.exists():
                    acknowledgement = self._read_control_json(response_relative)
                    if acknowledgement.get('protocol') != 1 or acknowledgement.get('id') != identifier or acknowledgement.get('pid') != pid or (acknowledgement.get('start_time') != status['start_time']) or (type(acknowledgement.get('ok')) is not bool) or (acknowledgement.get('state') not in {'accepted', 'executed', 'rejected'}):
                        raise PanelError('本地命令回执身份或格式不匹配，未确认执行结果；请勿重复提交。')
                    if acknowledgement['ok'] is not True or acknowledgement['state'] == 'rejected':
                        detail = str(acknowledgement.get('message', ''))[:500]
                        raise PanelError('服务端拒绝执行命令：' + (detail or '请查看服务端日志。'))
                    return
                current = self._read_file_control_status(pid)
                if current['start_time'] != status['start_time']:
                    raise PanelError('等待命令回执期间服务器进程已改变，请勿重复提交。')
                time.sleep(0.1)
            raise PanelError('等待服务端命令回执超时，结果尚未确认；请先查看日志，避免重复操作。')
        except OSError as error:
            raise PanelError('无法写入或读取本地命令通道：' + str(error)) from error
        finally:
            for relative in (request_relative, f'requests/{identifier}.tmp', response_relative):
                try:
                    self._checked_control_path(relative).unlink(missing_ok=True)
                except (OSError, PanelError):
                    pass

    def _run_powershell(self, script: Path, arguments: list[str], *, detached_output_name: str | None=None) -> None:
        powershell = Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        command = [str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), *arguments]
        access_violation_codes = {-1073741819, 3221225477}
        if detached_output_name:
            logs_root = self.server_root / 'logs'
            logs_root.mkdir(parents=True, exist_ok=True)
            stdout_path = logs_root / f'{detached_output_name}.stdout.log'
            stderr_path = logs_root / f'{detached_output_name}.stderr.log'
            for attempt in range(1, 4):
                with stdout_path.open('wb') as stdout_handle, stderr_path.open('wb') as stderr_handle:
                    if getattr(self, 'hide_launcher_windows', True):
                        from native_launch_job import snapshot, start_process
                        previous = snapshot(self)
                        if previous is not None and (previous['java_pid'] or previous['launcher_pids']):
                            raise PanelError('已有启动链仍在运行，未重复启动外部守护。')
                        result = start_process(self, command, None, stdout_handle, stderr_handle)
                        result.wait(timeout=30)
                    else:
                        result = subprocess.run(command, cwd=str(self.server_root), stdout=stdout_handle, stderr=stderr_handle, timeout=30, creationflags=CREATE_NO_WINDOW, check=False)
                if result.returncode not in access_violation_codes or attempt >= 3:
                    break
                self.log(f'Windows PowerShell 安全扫描进程异常退出，2 秒后自动重试（{attempt}/3）。', 'WARN')
                time.sleep(2)
            if result.returncode:
                stderr_text = stderr_path.read_text(encoding='mbcs', errors='replace').strip()
                stdout_text = stdout_path.read_text(encoding='mbcs', errors='replace').strip()
                raise PanelError(stderr_text or stdout_text or f'脚本退出代码 {result.returncode}')
            return
        for attempt in range(1, 4):
            result = subprocess.run(command, cwd=str(self.server_root), capture_output=True, text=True, encoding='mbcs', errors='replace', timeout=180, creationflags=CREATE_NO_WINDOW, check=False)
            if result.returncode not in access_violation_codes or attempt >= 3:
                break
            self.log(f'Windows PowerShell 安全扫描进程异常退出，2 秒后自动重试（{attempt}/3）。', 'WARN')
            time.sleep(2)
        if result.returncode:
            message = (result.stderr or result.stdout).strip()
            raise PanelError(message or f'脚本退出代码 {result.returncode}')

    def _check_startup_stop_requested(self) -> None:
        if not self._startup_waiting or not self._supports_startup_stop():
            return
        requested = self._startup_cancel_requested.is_set()
        if not requested:
            try:
                requested = self.stop_flag_path.read_text(encoding='ascii').startswith('startup-stop-requested')
            except (OSError, UnicodeError):
                pass
        if requested:
            self._startup_cancel_requested.set()
            raise StartupCancelled('已收到启动停止请求，正在等待监督和子进程退出。')

    def _start_without_watchdog(self) -> None:
        if self.validated_server_pid():
            return
        from native_launch_job import snapshot as job_snapshot, start_script, start_process
        prior_job = job_snapshot(self)
        if prior_job is not None and (prior_job['java_pid'] or prior_job['launcher_pids']):
            raise PanelError('服务器自带启动器或其子进程仍在运行，请先关闭原启动器后再启动。')
        launcher = self.server_root / self.launch_script
        if not launcher.is_file():
            raise PanelError(f'服务器启动脚本不存在：{launcher}')
        from native_managed_launch import build_launch, remember_launch
        managed = build_launch(self)
        arguments, environment = managed if managed is not None else ([os.environ.get('ComSpec', 'C:\\Windows\\System32\\cmd.exe'), '/d', '/c', str(launcher)], None)
        if managed is None and platform_profile(getattr(self, 'platform', 'vanilla'))['runtime'] == 'java' and self.java_path.is_file():
            environment = os.environ.copy()
            environment['JAVA_HOME'] = str(self.java_path.parent.parent)
            environment['PATH'] = str(self.java_path.parent) + os.pathsep + environment.get('PATH', '')
        logs = self.server_root / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / 'panel-launcher.stdout.log').open('wb') as stdout_handle, (logs / 'panel-launcher.stderr.log').open('wb') as stderr_handle:
            self._check_startup_stop_requested()
            previous = getattr(self, '_startup_launcher', None)
            if previous is not None and previous.poll() is not None and getattr(previous, 'stdin', None):
                previous.stdin.close()
            self._owned_direct_launch = None
            self._owned_script_launch = None
            self._owned_launch_job = None
            if managed is None:
                self._startup_launcher = start_script(self, arguments, environment, stdout_handle, stderr_handle)
            else:
                self._startup_launcher = start_process(self, arguments, environment, stdout_handle, stderr_handle, pipe_input=True, cwd=getattr(managed, 'cwd', self.server_root))
            if managed is not None:
                try:
                    self._owned_direct_launch = remember_launch(self, self._startup_launcher)
                except (OSError, ValueError, AttributeError):
                    self.log('未能保留本次直接启动的进程身份证据；退出时将使用保守状态检查。', 'WARN')
            else:
                from native_script_identity import remember_script_launch
                try:
                    self._owned_script_launch = remember_script_launch(self, self._startup_launcher)
                except (OSError, ValueError, AttributeError, TypeError):
                    self.log('未能保留原启动文件的进程身份证据；将使用保守状态检查。', 'WARN')
        self._startup_probe_at = 0.0

    def _startup_process_snapshot(self, *, force: bool=False) -> dict[str, Any] | None:
        """Find this instance before its game port opens; unknown is not absent."""
        from native_launch_job import snapshot as job_snapshot
        try:
            job = job_snapshot(self)
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        if job is not None:
            if not job['java_pid'] and (not job['launcher_pids']) and (getattr(self, '_owned_direct_launch', None) is not None):
                from native_managed_launch import owned_startup_snapshot
                try:
                    return owned_startup_snapshot(self)
                except (OSError, ValueError, TypeError, AttributeError):
                    return None
            return job
        from native_managed_launch import owned_startup_snapshot
        try:
            owned = owned_startup_snapshot(self)
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        if owned is not None:
            return owned
        if self.platform_profile()['runtime'] in {'native', 'php'}:
            from native_platform_launch import process_snapshot
            return process_snapshot(self)
        with self._startup_probe_lock:
            if not force and time.monotonic() - self._startup_probe_at < 3.0:
                return self._startup_probe_result
            result = None
            powershell = Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            query = '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $ErrorActionPreference = \'Stop\'; @(Get-CimInstance Win32_Process -Filter "Name=\'java.exe\' OR Name=\'javaw.exe\' OR Name=\'cmd.exe\' OR Name=\'powershell.exe\' OR Name=\'pwsh.exe\' OR Name=\'python.exe\' OR Name=\'pythonw.exe\'" | Select-Object ProcessId,Name,ExecutablePath,CommandLine) | ConvertTo-Json -Compress'
            try:
                response = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', query], capture_output=True, text=True, encoding='utf-8-sig', errors='replace', timeout=8, creationflags=CREATE_NO_WINDOW, check=False)
                if response.returncode == 0:
                    rows = json.loads(response.stdout or '[]')
                    if isinstance(rows, dict):
                        rows = [rows]
                    if not isinstance(rows, list):
                        raise ValueError('Invalid process snapshot')
                    result = {'java_pid': 0, 'launcher_pids': [], 'watchdog_pids': []}
                    marker = re.compile('(?:^|\\s)"?' + re.escape(f'-dqizhang.panel.server_id={self.server_id.lower()}') + '"?(?:\\s|$)')
                    launcher = str(self.server_root / self.launch_script).lower().replace('\\', '/')
                    watchdogs = [str(self.server_root / name).lower().replace('\\', '/') for name in ('qizhang-server-watchdog.py', 'qizhang-server-watchdog.ps1', 'qizhang-watchdog-launcher.ps1')]
                    expected_java = str(self.java_path.resolve()).lower() if self.java_path.is_file() else ''
                    for row in rows:
                        command = str(row.get('CommandLine') or '').lower().replace('\\', '/')
                        executable = str(row.get('ExecutablePath') or '')
                        pid = int(row.get('ProcessId') or 0)
                        if not pid:
                            continue
                        if not command:
                            result = None
                            break
                        if str(row.get('Name') or Path(executable).name).lower() in {'java.exe', 'javaw.exe'}:
                            if not executable:
                                result = None
                                break
                            same_java = not expected_java or str(Path(executable).resolve()).lower() == expected_java
                            if marker.search(command) and (not same_java):
                                result = None
                                break
                            if marker.search(command) and same_java:
                                result['java_pid'] = pid
                            elif same_java and '-dqizhang.panel.server_id=' not in command:
                                result = None
                                break
                        elif launcher in command:
                            result['launcher_pids'].append(pid)
                        elif any((path in command for path in watchdogs)):
                            result['watchdog_pids'].append(pid)
            except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                pass
            self._startup_probe_result = result
            self._startup_probe_at = time.monotonic()
            return result

    def _clear_inactive_startup(self, *, recovered: bool=False) -> None:
        """Only call after confirming no instance Java/launcher remains."""
        self.starting_flag_path.unlink(missing_ok=True)
        self._startup_waiting = False
        with self._status_lock:
            self._status.update(starting=False, running=False, ready=False, pid=0, memory_mb=0.0, cpu_percent=0.0, uptime_seconds=0, online_count=0, online_players=[], updated_at=datetime.now().isoformat(timespec='seconds'))
            self._status.pop('monitor_error', None)
        if recovered:
            notice = '已确认本实例 Java、启动器和守护均未运行；已清理上次启动遗留标记，可以重新启动。'
            self._startup_notices.append('[面板/WARN] ' + notice)
            self.log(notice, 'WARN')

    def reconcile_startup_state(self, *, force: bool=False) -> bool:
        """Clear a stale start only after fresh, serialized process proof.

        Manual closure outside the panel must not require importing the server
        again. An old timeout/error stays in operation history; it is not a live
        process. Unknown snapshots and live related processes keep the marker.
        """
        with self._status_lock:
            cached_starting = bool(self._status.get('starting'))
        if not self.starting_flag_path.exists() and (not (force and cached_starting)):
            return False
        if not self._mutation_lock.acquire(blocking=False):
            return False
        try:
            with self._operation_lock, self._shutdown_countdown_lock:
                if self._operation.get('active') or self._startup_waiting or self._shutdown_countdown.get('active') or self.maintenance_flag_path.exists():
                    return False
                marker_before = self.starting_flag_path.stat() if self.starting_flag_path.exists() else None
                launcher = self._startup_launcher
                if launcher is not None and launcher.poll() is None:
                    return False
                if getattr(self, '_owned_launch_job', None) is None and getattr(self, '_owned_direct_launch', None) is None and (not self._has_panel_startup_identity()):
                    return False
                if self.validated_server_pid() or self._read_watchdog_pid(validate_command=True):
                    return False
                activity = self._startup_process_snapshot(force=True)
                if not isinstance(activity, dict) or not {'java_pid', 'launcher_pids', 'watchdog_pids'}.issubset(activity) or activity['java_pid'] or activity['launcher_pids'] or activity['watchdog_pids']:
                    return False
                marker_after = self.starting_flag_path.stat() if self.starting_flag_path.exists() else None
                if marker_before != marker_after or self._operation.get('active') or self._startup_waiting or self._shutdown_countdown.get('active') or self.maintenance_flag_path.exists():
                    return False
                self._clear_inactive_startup(recovered=True)
                return True
        except (OSError, ValueError, TypeError, AttributeError, PanelError):
            return False
        finally:
            self._mutation_lock.release()

    def _has_panel_startup_identity(self) -> bool:
        """Only generated, identity-tagged entrypoints allow stale-lock recovery.

        An arbitrary imported script may detach an unmarked GUI/launcher. A
        missing port and an exited cmd alone cannot prove that script is idle.
        """
        if self.launch_script == 'qizhang-platform-start.bat':
            try:
                from native_platform_launch import build_launch
                return build_launch(self) is not None
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                return False
        try:
            script = (self.server_root / self.launch_script).read_text(encoding='utf-8-sig')
            marker = f'-Dqizhang.panel.server_id={self.server_id}'
            if self.launch_script == 'qizhang-managed-start.bat' and marker in script:
                spec = read_json(self.server_root / 'qizhang-startup.json', {})
                powershell = (self.server_root / 'qizhang-managed-start.ps1').read_text(encoding='utf-8-sig')
                return spec.get('server_id') == self.server_id and 'qizhang-managed-start.ps1' in script and ("'-Dqizhang.panel.server_id=' + $cfg.server_id" in powershell) and ('$start.FileName = $java' in powershell) and ('[System.Diagnostics.Process]::Start($start)' in powershell)
            if self.launch_script in {'start-server.bat', 'qizhang-imported-start.bat'} and marker in script:
                return True
            if self.launch_script != 'qizhang-imported-start.bat' or 'qizhang-imported-start.ps1' not in script:
                return False
            spec = read_json(self.server_root / 'qizhang-import-launch.json', {})
            powershell = (self.server_root / 'qizhang-imported-start.ps1').read_text(encoding='utf-8-sig')
            return spec.get('server_id') == self.server_id and "'-Dqizhang.panel.server_id=' + $cfg.server_id" in powershell and ('& $java @javaArgs' in powershell)
        except (OSError, UnicodeError, AttributeError):
            return False

    def ensure_not_starting(self) -> None:
        if not self.starting_flag_path.exists():
            return
        if self.reconcile_startup_state(force=True):
            return
        if self.validated_server_pid():
            self.starting_flag_path.unlink(missing_ok=True)
            return
        launcher = self._startup_launcher
        if not False and self._has_panel_startup_identity() and (launcher is None or launcher.poll() is not None):
            activity = self._startup_process_snapshot(force=True)
            if activity is not None and (not activity['java_pid']) and (not activity['launcher_pids']) and (not activity['watchdog_pids']):
                self._clear_inactive_startup(recovered=True)
                return
        port = self.get_server_properties().get('server-port', '25565')
        raise PanelError(f'服务器正在启动且尚未开放 {port} 端口，暂时不能执行此操作。')

    def start_server(self) -> None:
        with self._operation_lock:
            if getattr(self, '_native_exit_pending', False):
                raise PanelError('面板正在退出以安装更新，暂不接受新的服务器操作。')
        if self.maintenance_flag_path.exists():
            raise PanelError('服务器正在备份或恢复，暂时不能启动。')
        self.ensure_not_starting()
        if self.validated_server_pid():
            raise PanelError('服务器已经在运行。')
        self._capture_startup_logs()
        with self._operation_lock:
            if getattr(self, '_native_exit_pending', False):
                raise PanelError('面板正在退出以安装更新，未创建服务器进程。')
            if self._startup_cancel_requested.is_set():
                raise StartupCancelled('启动已取消，未创建服务器进程。')
            self.stop_flag_path.unlink(missing_ok=True)
            self.starting_flag_path.write_text('panel-start', encoding='ascii')
            self._startup_waiting = True
            with self._status_lock:
                self._status.update(starting=True, running=False, ready=False, pid=0)
        try:
            self._start_without_watchdog()
        except Exception as error:
            if (self._supports_startup_stop() or self._startup_stop_owned is not None) and self._startup_cancel_requested.is_set():
                self._wait_for_new_server_ready(0, 360)
            self.starting_flag_path.unlink(missing_ok=True)
            self._startup_waiting = False
            raise PanelError(self._startup_failure_message(str(error))) from error
        new_pid = self._wait_for_new_server_ready(0, 360)
        if not new_pid:
            raise PanelError(self._startup_failure_message('已提交开服，但服务器在 360 秒内尚未输出 Done 并完全启动；启动标记已保留，面板会阻止误备份。'))
        self.starting_flag_path.unlink(missing_ok=True)
        self.log(f'服务器启动完成，Java PID={new_pid}。')

    @contextmanager
    def _stop_receipt_process_guard(self, pid: int, *, enabled: bool=True):
        """Optional evidence for an ambiguous stop receipt, never another command."""
        if not enabled:
            yield None
            return
        try:
            from native_command_bridge import _process_guard
            created = self._process_creation_time(pid)
            expected_start = int(datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp() * 1000)
            context = _process_guard(pid, expected_start)
            lease = context.__enter__()
        except Exception:
            yield None
            return
        try:
            yield lease
        finally:
            context.__exit__(None, None, None)

    def _stop_receipt_error(self, lease, error: Exception) -> Exception:
        """Refine a failed receipt only with original-process exit evidence."""
        if lease is None:
            return error
        try:
            if not lease.has_exited():
                return error
            activity = self._startup_process_snapshot(force=True)
            if activity is None or activity['java_pid']:
                return error
        except Exception:
            return error
        message = '服务器已退出；命令回执未确认，请查看保存日志。'
        self.log(message + ' 原命令通道错误：' + str(error), 'WARN')
        return PanelError(message)

    def stop_server(self, restart: bool=False) -> None:
        pid = self.validated_server_pid()
        if not pid:
            raise PanelError('服务器当前未运行。')
        if self.platform_profile()['family'] != 'java':
            self._planned_shutdown_until = time.monotonic() + 420.0
            self.send_command(self.platform_profile()['stop_command'])
            self.log('已提交该平台的正常停服命令，等待进程退出。')
            return
        self._planned_shutdown_until = time.monotonic() + 420.0
        with self._operation_lock:
            diagnose_receipt = not restart and (not (self._operation.get('active') and self._operation.get('name') in STARTUP_OPERATION_NAMES))
        with self._stop_receipt_process_guard(pid, enabled=diagnose_receipt) as lease:
            try:
                if not self.control_script:
                    action_text = '重启' if restart else '关闭'
                    self.send_command('tellraw @a ' + json.dumps({'text': f'<全服通告> 服务器将在10秒后{action_text} <关闭时间> 10秒', 'color': 'gold'}, ensure_ascii=True, separators=(',', ':')))
                    time.sleep(10)
                    self.send_command('save-all flush')
                    self.send_command('stop')
                else:
                    action = 'Restart' if restart else 'Stop'
                    try:
                        self._run_powershell(self.server_root / self.control_script, ['-Action', action, '-ExpectedPid', str(pid)])
                    except Exception:
                        if not restart:
                            self.stop_flag_path.unlink(missing_ok=True)
                        raise
            except Exception as error:
                refined = self._stop_receipt_error(lease, error)
                if refined is error:
                    raise
                raise refined from error
        self.log('已提交重启请求。' if restart else '已提交安全关服请求。')

    @staticmethod
    def _shutdown_countdown_text(seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds >= 60 and seconds % 60 == 0:
            return f'{seconds // 60}分钟'
        return f'{seconds}秒'

    @staticmethod
    def _shutdown_countdown_should_announce(remaining: int, requested: int) -> bool:
        if remaining == requested or remaining <= 30:
            return True
        return remaining % 2 == 0

    def _set_shutdown_countdown_state(self, **updates: Any) -> None:
        with self._shutdown_countdown_lock:
            self._shutdown_countdown.update(updates)

    def _shutdown_actionbar_text(self, remaining: int) -> str:
        remaining_text = self._shutdown_countdown_text(remaining)
        content = [{'text': '<全服通告> ', 'color': 'gold', 'bold': True}, {'text': f'服务器将在 {remaining_text}后关闭', 'color': 'red', 'bold': True}]
        return json.dumps(content, ensure_ascii=True, separators=(',', ':'))

    def _update_shutdown_actionbar(self, remaining: int) -> None:
        if self.platform_profile()['family'] != 'java':
            return
        self.send_command('title @a actionbar ' + self._shutdown_actionbar_text(remaining))

    def _send_shutdown_cancel_notice(self) -> None:
        if self.platform_profile()['family'] != 'java':
            return
        self.send_command('title @a actionbar {"text":""}')
        self.send_command('tellraw @a ' + json.dumps({'text': '<全服通告> 已暂停停服，服务器将继续运行。', 'color': 'green', 'bold': True}, ensure_ascii=True, separators=(',', ':')))

    def _submit_countdown_stop(self, expected_pid: int) -> None:
        current_pid = self.validated_server_pid()
        if current_pid != expected_pid:
            raise PanelError('倒计时结束前服务器进程发生变化，已拒绝向新进程提交关服。')
        self._planned_shutdown_until = time.monotonic() + 420.0
        self.stop_flag_path.write_text('panel-countdown-stop', encoding='ascii')
        stop_submitted = False
        with self._stop_receipt_process_guard(expected_pid) as lease:
            try:
                if self.platform_profile()['family'] == 'java':
                    self.send_command('save-all flush')
                    self.send_command('title @a actionbar {"text":""}')
                    time.sleep(2)
                if self.validated_server_pid() != expected_pid:
                    raise PanelError('保存后服务器进程发生变化，已取消剩余关服指令。')
                self.send_command(self.platform_profile()['stop_command'])
                stop_submitted = True
            except Exception as error:
                if not stop_submitted and self.validated_server_pid() == expected_pid:
                    self.stop_flag_path.unlink(missing_ok=True)
                    self._planned_shutdown_until = 0.0
                refined = self._stop_receipt_error(lease, error)
                if refined is error:
                    raise
                raise refined from error
        if not self._wait_process_exit(expected_pid, 300):
            raise PanelError('服务器进程在 300 秒内未完全退出。')
        self.starting_flag_path.unlink(missing_ok=True)
        self.log('倒计时结束，服务器已安全关闭。')

    def _run_shutdown_countdown(self, *, expected_pid: int, requested_seconds: int, deadline: float, cancel_event: threading.Event) -> None:
        operation_name = '倒计时关闭服务器'
        try:
            notice_text = self._shutdown_countdown_text(requested_seconds)
            notice = f'<全服通告> 通知内容：服务器即将安全关闭 关闭时间：{notice_text}后'
            if self.platform_profile()['family'] == 'java':
                self.send_command('tellraw @a ' + json.dumps({'text': notice, 'color': 'gold', 'bold': True}, ensure_ascii=True, separators=(',', ':')))
            last_announced = -1
            while True:
                remaining = max(0, int(deadline - time.monotonic() + 0.999))
                if cancel_event.is_set():
                    self._send_shutdown_cancel_notice()
                    self._set_shutdown_countdown_state(active=False, phase='cancelled', remaining_seconds=remaining, can_cancel=False, message='停服倒计时已取消。')
                    self._set_operation(False, operation_name, '停服倒计时已取消。', True, True)
                    self.log('停服倒计时已由面板取消。')
                    return
                if remaining <= 0:
                    break
                self._set_shutdown_countdown_state(remaining_seconds=remaining, message=f'服务器将在 {self._shutdown_countdown_text(remaining)}后关闭。')
                with self._operation_lock:
                    if self._operation.get('active'):
                        self._operation['message'] = f'停服倒计时：{self._shutdown_countdown_text(remaining)}'
                if remaining != last_announced and self._shutdown_countdown_should_announce(remaining, requested_seconds):
                    self._update_shutdown_actionbar(remaining)
                    last_announced = remaining
                cancel_event.wait(min(1.0, max(0.05, deadline - time.monotonic())))
            with self._shutdown_countdown_lock:
                if cancel_event.is_set():
                    self._shutdown_countdown['remaining_seconds'] = 0
                    self._shutdown_countdown['message'] = '正在取消停服…'
                    continue_cancel = True
                else:
                    self._shutdown_countdown.update({'phase': 'stopping', 'remaining_seconds': 0, 'can_cancel': False, 'message': '倒计时结束，正在保存并关闭服务器…'})
                    continue_cancel = False
            if continue_cancel:
                self._send_shutdown_cancel_notice()
                self._set_shutdown_countdown_state(active=False, phase='cancelled', can_cancel=False, message='停服倒计时已取消。')
                self._set_operation(False, operation_name, '停服倒计时已取消。', True, True)
                return
            self.send_command('title @a actionbar ' + json.dumps({'text': '正在保存并关闭服务器…', 'color': 'gold', 'bold': True}, ensure_ascii=True, separators=(',', ':')))
            self._submit_countdown_stop(expected_pid)
            self._set_shutdown_countdown_state(active=False, phase='completed', remaining_seconds=0, can_cancel=False, message='服务器已安全关闭。')
            self._set_operation(False, operation_name, '服务器已安全关闭。', True, True)
        except Exception as error:
            self._set_shutdown_countdown_state(active=False, phase='failed', can_cancel=False, message=f'停服倒计时失败：{error}')
            self._set_operation(False, operation_name, str(error), False, True)
            self.log(f'倒计时关闭服务器失败：{error}', 'ERROR')
        finally:
            with self._shutdown_countdown_lock:
                if self._shutdown_countdown_cancel is cancel_event:
                    self._shutdown_countdown_cancel = None
                if self._shutdown_countdown_thread is threading.current_thread():
                    self._shutdown_countdown_thread = None

    def start_shutdown_countdown(self, seconds: Any) -> dict[str, Any]:
        if isinstance(seconds, bool):
            raise PanelError('停服倒计时必须填写整数秒数。')
        try:
            requested_seconds = int(str(seconds).strip())
        except (TypeError, ValueError) as error:
            raise PanelError('停服倒计时必须填写整数秒数。') from error
        if requested_seconds < 5 or requested_seconds > 3600:
            raise PanelError('停服倒计时只能设置为 5～3600 秒。')
        with self._mutation_lock:
            self.ensure_idle()
            expected_pid = self.validated_server_pid()
            if not expected_pid:
                raise PanelError('服务器当前未运行，无法发送停服倒计时。')
            with self._shutdown_countdown_lock:
                if self._shutdown_countdown.get('active'):
                    raise PanelError('已有停服倒计时正在进行，请先取消。')
                self._reserve_operation('倒计时关闭服务器')
                cancel_event = threading.Event()
                now = datetime.now()
                deadline = time.monotonic() + requested_seconds
                self._shutdown_countdown = {'active': True, 'phase': 'countdown', 'requested_seconds': requested_seconds, 'remaining_seconds': requested_seconds, 'started_at': now.isoformat(timespec='seconds'), 'ends_at': (now + timedelta(seconds=requested_seconds)).isoformat(timespec='seconds'), 'can_cancel': True, 'message': f'服务器将在 {self._shutdown_countdown_text(requested_seconds)}后关闭。'}
                thread = threading.Thread(target=self._run_shutdown_countdown, kwargs={'expected_pid': expected_pid, 'requested_seconds': requested_seconds, 'deadline': deadline, 'cancel_event': cancel_event}, name=f'QiZhang-Shutdown-Countdown-{self.server_id}', daemon=True)
                self._shutdown_countdown_cancel = cancel_event
                self._shutdown_countdown_thread = thread
                try:
                    thread.start()
                except Exception:
                    self._shutdown_countdown_cancel = None
                    self._shutdown_countdown_thread = None
                    self._shutdown_countdown.update({'active': False, 'phase': 'failed', 'can_cancel': False, 'message': '无法启动停服倒计时线程。'})
                    self._set_operation(False, '倒计时关闭服务器', '无法启动停服倒计时线程。', False, True)
                    raise
                result = json.loads(json.dumps(self._shutdown_countdown))
        self.log(f'已启动停服倒计时：{self._shutdown_countdown_text(requested_seconds)}。')
        return result

    def cancel_shutdown_countdown(self) -> dict[str, Any]:
        with self._shutdown_countdown_lock:
            if not self._shutdown_countdown.get('active'):
                raise PanelError('当前没有正在进行的停服倒计时。')
            if not self._shutdown_countdown.get('can_cancel'):
                raise PanelError('倒计时已经结束，服务器正在保存并关闭，无法取消。')
            cancel_event = self._shutdown_countdown_cancel
            if cancel_event is None:
                raise PanelError('停服倒计时状态异常，无法提交取消请求。')
            self._shutdown_countdown['can_cancel'] = False
            self._shutdown_countdown['message'] = '正在取消停服倒计时…'
            cancel_event.set()
            return json.loads(json.dumps(self._shutdown_countdown))

    def _wait_for_new_server(self, previous_pid: int, timeout: float=360) -> int:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            pid = self.validated_server_pid()
            if pid and pid != previous_pid:
                return pid
            time.sleep(1)
        return 0

    def _supports_supervisor_startup_stop(self) -> bool:
        capabilities = read_json(self.server_root / 'qizhang-supervisor-capabilities.json', {})
        return bool(False and isinstance(capabilities, dict) and (capabilities.get('stop_during_start') is True))

    def _owned_startup_stop_target(self):
        """Require the exact retained process and writable input, never a PID guess."""
        from native_managed_launch import owned_process_pid
        from native_console_pipe import _owned, ConsolePipeError
        try:
            pid = owned_process_pid(self)
            return _owned(self, pid) if pid else None
        except (OSError, ValueError, AttributeError, TypeError, ConsolePipeError):
            return None

    def _supports_startup_stop(self) -> bool:
        return self._supports_supervisor_startup_stop() or self._owned_startup_stop_target() is not None or self._hidden_startup_job() is not None

    def _hidden_startup_job(self):
        from native_launch_job import _owned
        try:
            job = _owned(self)
            return job if job is not None and job.desktop is not None else None
        except (OSError, ValueError, AttributeError):
            return None

    def _wait_for_hidden_startup_stop(self, job, timeout=30):
        from native_launch_job import close_windows, snapshot
        if self._hidden_startup_job() is not job:
            raise PanelError('启动器进程身份已变化，未关闭其他窗口。')
        close_windows(self)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._hidden_startup_job() is not job:
                raise PanelError('启动器身份已变化，未清理启动状态。')
            state = snapshot(self)
            if state is not None and (not state['java_pid']) and (not state['launcher_pids']):
                self._clear_inactive_startup()
                raise StartupCancelled('原启动器及其子进程已正常关闭，启动已取消。')
            time.sleep(0.2)
        raise PanelError('已请求关闭隐藏启动器，但它尚未退出；可能正在等待其自身的确认。未强杀服务器，请查看日志。')

    def _wait_for_owned_startup_stop(self, timeout: float=300) -> None:
        """Startup worker sends one normal stop, then confirms exit; no retry/kill."""
        from native_managed_launch import owned_process_pid
        from native_console_pipe import send_command, ConsolePipeError
        owned = self._startup_stop_owned
        if owned is None or not self._startup_cancel_requested.is_set():
            return
        self._planned_shutdown_until = time.monotonic() + max(0.0, timeout) + 30.0
        with self._operation_lock:
            if self._startup_stop_attempted:
                raise PanelError('本次启动的停服命令已尝试提交，未自动重发；请检查控制台与进程状态。')
            self._startup_stop_attempted = True
        try:
            if self._owned_direct_launch is not owned:
                raise PanelError('启动实例身份已变化，未向其他进程发送停服命令。')
            pid = owned_process_pid(self)
            if pid:
                if self._owned_startup_stop_target() is not owned:
                    raise PanelError('无法确认本次启动进程的输入通道，未发送停服命令。')
                if not send_command(self, pid, self.platform_profile()['stop_command']):
                    raise PanelError('本次启动没有可用的面板输入通道，未发送停服命令。')
        except (OSError, ValueError, AttributeError, TypeError, ConsolePipeError) as error:
            raise PanelError('启动中停止未确认提交，未自动重发或强制结束；启动标记保留。' + str(error)) from error
        with self._operation_lock:
            self._operation['message'] = '已提交正常停服请求，等待本次启动进程及关联进程退出。'
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                if self._owned_direct_launch is not owned:
                    raise OSError('owned launch replaced')
                pid = owned_process_pid(self)
            except (OSError, ValueError, AttributeError, TypeError) as error:
                raise PanelError('停止启动时进程身份无法确认；未清理启动标记，请检查控制台。') from error
            if not pid:
                activity = self._startup_process_snapshot(force=True)
                if activity is not None and (not activity['java_pid']) and (not activity['launcher_pids']) and (not activity['watchdog_pids']):
                    self._clear_inactive_startup()
                    raise StartupCancelled('启动已取消，本次面板启动的进程及关联启动进程已确认退出。')
            if time.monotonic() >= deadline:
                raise PanelError('停止启动等待超时，进程仍在运行或退出状态无法确认；未强杀、未重发，启动标记保留。')
            time.sleep(0.2)

    def _stop_owned_incomplete_startup(self, owned) -> None:
        """The startup operation timed out, but its exact process is still alive."""
        with self._operation_lock:
            self._startup_stop_owned = owned
            self._startup_cancel_requested.set()
        self._wait_for_owned_startup_stop()

    def _startup_processes(self) -> set[int]:
        """Include the launcher before Java has opened its server port."""
        result: set[int] = set()
        watchdog = self._read_watchdog_pid(validate_command=True)
        if watchdog:
            result.add(watchdog)
        try:
            console = int((self.server_root / '.qizhang-console.pid').read_text(encoding='ascii').strip())
        except (OSError, ValueError):
            return result
        command = self._process_command_line(console).lower().replace('\\', '/')
        launcher = str(self.server_root / self.launch_script).lower().replace('\\', '/')
        if console > 0 and Path(self.process_image_name(console)).name.lower() == 'cmd.exe' and (launcher in command):
            result.add(console)
        return result

    @staticmethod
    def _startup_log_fingerprint(path: Path) -> tuple[Any, ...] | None:
        try:
            stat = path.stat()
            with path.open('rb') as handle:
                prefix = handle.read(min(256, stat.st_size))
            return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, prefix)
        except OSError:
            return None

    def _capture_startup_logs(self) -> None:
        logs = self.server_root / 'logs'
        self._startup_log_baseline = {path: self._startup_log_fingerprint(path) for path in (self.latest_log_path, logs / 'watchdog.log', logs / 'watchdog-python.stderr.log', logs / 'watchdog-launcher.stderr.log', logs / 'panel-launcher.stdout.log', logs / 'panel-launcher.stderr.log')}

    def _startup_failure_message(self, message: str) -> str:
        excerpts: list[str] = []
        for path, before in self._startup_log_baseline.items():
            after = self._startup_log_fingerprint(path)
            if after is None or before == after:
                continue
            offset = 0
            if before is not None and before[:2] == after[:2] and (after[2] >= before[2]) and after[4].startswith(before[4]):
                offset = before[2]
            try:
                with path.open('rb') as handle:
                    handle.seek(max(offset, after[2] - 8192))
                    fresh = '\n'.join((decode_server_log(line) for line in handle.read(8192).splitlines()))
            except OSError:
                continue
            lines = [line.strip() for line in fresh.splitlines() if line.strip()]
            if lines:
                excerpts.append(f'{path.name}：' + ' | '.join(lines[-5:])[-1200:])
        if excerpts:
            return message + '\n本次启动新增日志末段：\n' + '\n'.join(excerpts)[-2400:]
        return message

    def _wait_for_new_server_ready(self, previous_pid: int, timeout: float=360) -> int:
        started = time.monotonic()
        deadline = started + max(0.0, timeout)
        supervised = self._supports_supervisor_startup_stop()
        absent_since: float | None = None
        tracked: set[int] = set()
        seen_process = False
        while True:
            if self._startup_cancel_requested.is_set() and getattr(self, '_startup_stop_job', None) is not None:
                self._wait_for_hidden_startup_stop(self._startup_stop_job)
            if self._startup_cancel_requested.is_set() and self._startup_stop_owned is not None:
                self._wait_for_owned_startup_stop()
            now = time.monotonic()
            cancelling = (supervised or self._startup_stop_owned is not None or getattr(self, '_startup_stop_job', None) is not None) and (self._startup_cancel_requested.is_set() or self.stop_flag_path.exists())
            if now >= deadline and (not cancelling):
                with self._operation_lock:
                    cancelling = (supervised or self._startup_stop_owned is not None or getattr(self, '_startup_stop_job', None) is not None) and (self._startup_cancel_requested.is_set() or self.stop_flag_path.exists())
                    if not cancelling:
                        self._startup_waiting = False
                        return 0
            pid = self.validated_server_pid()
            launcher = self._startup_launcher
            if not pid and now - started > 15 and (self._hidden_startup_job() is not None) and (getattr(self, '_owned_direct_launch', None) is None) and (not self._startup_cancel_requested.is_set()):
                with self._operation_lock:
                    self._operation['message'] = '原启动器已在隐藏桌面运行，尚未确认游戏服务端启动。如果它需要再次点击开服，请先停止启动，再选择可直接运行的服务端入口；也可在高级设置取消隐藏后重试。'
            if not supervised and launcher is not None and (launcher.poll() is not None) and (not pid) and (getattr(self, '_owned_launch_job', None) is not None or self._has_panel_startup_identity()):
                activity = self._startup_process_snapshot()
                if activity is not None and (not activity['java_pid']) and (not activity['launcher_pids']) and (not activity['watchdog_pids']):
                    if absent_since is None:
                        absent_since = now
                    if now - absent_since >= 3.0:
                        self._clear_inactive_startup()
                        raise PanelError(self._startup_failure_message(f'启动失败：启动器已退出（退出代码 {launcher.returncode}），本实例没有运行中的 Java 或启动进程。请查看控制台中的启动器错误。'))
                else:
                    absent_since = None
            if supervised:
                current = self._startup_processes()
                if pid:
                    current.add(pid)
                tracked = {known for known in tracked if self.process_exists(known)} | current
                if tracked:
                    seen_process = True
                    absent_since = None
                else:
                    if absent_since is None:
                        absent_since = now
                    grace = 3.0 if seen_process else 10.0
                    if now - absent_since >= grace:
                        with self._operation_lock:
                            cancelling = self._startup_cancel_requested.is_set() or self.stop_flag_path.exists()
                            self._startup_waiting = False
                            self.starting_flag_path.unlink(missing_ok=True)
                        with self._status_lock:
                            self._status.update(starting=False, running=False, ready=False, pid=0)
                        if cancelling:
                            raise StartupCancelled('启动已取消，监督和本实例子进程已全部退出。')
                        raise PanelError(self._startup_failure_message('启动失败：本实例监督及启动子进程已退出，没有新的 Java 进程完成启动。'))
                if cancelling:
                    self._startup_cancel_requested.set()
                    with self._operation_lock:
                        self._operation['message'] = '停止请求已排队；正在等待本实例安全关闭，监督和子进程全部退出后才完成。'
                    time.sleep(1)
                    continue
            with self._status_lock:
                ready_pid = int(self._status.get('pid', 0) or 0)
                ready = bool(self._status.get('ready', False))
            if pid and pid != previous_pid and ready and (ready_pid == pid):
                with self._operation_lock:
                    if (supervised or self._startup_stop_owned is not None or getattr(self, '_startup_stop_job', None) is not None) and (self._startup_cancel_requested.is_set() or self.stop_flag_path.exists()):
                        continue
                    self._startup_waiting = False
                    return pid
            time.sleep(1)

    def safe_stop_server(self) -> None:
        original_pid = self.validated_server_pid()
        if not original_pid:
            raise PanelError('服务器当前未运行。')
        self.stop_server(restart=False)
        if not self._wait_process_exit(original_pid, 300):
            raise PanelError('服务器进程在 300 秒内未完全退出。')
        self.starting_flag_path.unlink(missing_ok=True)
        self.log('服务器已安全关闭，Java 进程已完全退出。')

    def restart_server(self) -> None:
        original_pid = self.validated_server_pid()
        if not original_pid:
            raise PanelError('服务器当前未运行。')
        self.ensure_not_starting()
        self._capture_startup_logs()
        self.starting_flag_path.write_text('panel-restart', encoding='ascii')
        try:
            self.stop_server(restart=False)
        except Exception:
            if self.validated_server_pid() == original_pid:
                self.starting_flag_path.unlink(missing_ok=True)
            self.stop_flag_path.unlink(missing_ok=True)
            raise
        if not self._wait_process_exit(original_pid, 300):
            self.stop_flag_path.unlink(missing_ok=True)
            raise PanelError('原服务器进程在 300 秒内未退出，重启未完成。')
        with self._operation_lock:
            self._startup_waiting = True
        self.stop_flag_path.unlink(missing_ok=True)
        self._start_without_watchdog()
        new_pid = self._wait_for_new_server_ready(original_pid, 360)
        if not new_pid:
            raise PanelError(self._startup_failure_message('原服务器已关闭，但新服务器在 360 秒内尚未输出 Done 并完全启动；启动标记已保留，面板会阻止误备份。'))
        self.starting_flag_path.unlink(missing_ok=True)
        self.log(f'服务器重启完成，新 Java PID={new_pid}。')

    def stop_watchdog_only(self) -> None:
        pid = self._read_watchdog_pid(validate_command=True)
        if not pid:
            return
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, creationflags=CREATE_NO_WINDOW, check=False)
        try:
            self.watchdog_pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.log('自动重启守护已停用。')

    def force_stop(self) -> None:
        pid = self.validated_server_pid()
        self.stop_flag_path.write_text('panel-force-stop', encoding='ascii')
        if pid:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=CREATE_NO_WINDOW, check=False)
        self.stop_watchdog_only()
        self.starting_flag_path.unlink(missing_ok=True)
        self.log('已执行强制停止；该操作不保证保存最后几秒的数据。', 'WARN')

    def _set_operation(self, active: bool, name: str, message: str, ok: bool, finished: bool=False, cancelled: bool=False) -> None:
        with self._operation_lock:
            if active:
                self._startup_cancel_requested.clear()
                self._startup_stop_owned = None
                self._startup_stop_job = None
                self._startup_stop_attempted = False
                self._startup_waiting = False
                self._operation = {'id': uuid.uuid4().hex, 'active': True, 'name': name, 'message': message, 'started_at': datetime.now().isoformat(timespec='seconds'), 'finished_at': None, 'ok': True, 'progress': None, 'cancelled': False}
            else:
                progress = self._operation.get('progress')
                if isinstance(progress, dict) and finished:
                    progress['active'] = False
                    progress['updated_at'] = datetime.now().isoformat(timespec='seconds')
                    if ok:
                        progress.update({'stage': 'completed', 'stage_label': '链式维护完成' if name == '链式维护备份' else '备份完成', 'percent': 100.0, 'eta_seconds': 0, 'current_file': '', 'estimated_finish_at': datetime.now().isoformat(timespec='seconds'), 'indeterminate': False})
                    else:
                        progress.update({'stage': 'failed', 'stage_label': '链式维护失败' if name == '链式维护备份' else '备份失败', 'eta_seconds': None, 'estimated_finish_at': None, 'indeterminate': False})
                self._operation.update({'active': False, 'message': message, 'ok': ok, 'cancelled': cancelled, 'finished_at': datetime.now().isoformat(timespec='seconds') if finished else None})
            if name in STARTUP_OPERATION_NAMES:
                self._last_startup_operation = json.loads(json.dumps(self._operation))

    def _set_operation_progress(self, *, mode: str, stage: str, stage_label: str, percent: float, elapsed_seconds: float, processed_bytes: int=0, total_bytes: int=0, processed_files: int=0, total_files: int=0, speed_bps: float=0.0, eta_seconds: float | None=None, current_file: str='', archive_bytes: int=0, indeterminate: bool=False) -> None:
        """Publish a JSON-safe snapshot for the status API and web UI."""
        now = datetime.now()
        safe_eta: int | None = None
        if eta_seconds is not None and eta_seconds >= 0:
            safe_eta = min(7 * 24 * 60 * 60, int(round(eta_seconds)))
        safe_percent = round(max(0.0, min(100.0, float(percent))), 1)
        safe_current = str(current_file or '').replace('\\', '/')[-240:]
        message = f'{stage_label} {safe_percent:.1f}%'
        with self._operation_lock:
            if not self._operation.get('active'):
                return
            self._operation['message'] = message
            self._operation['progress'] = {'active': True, 'kind': 'backup', 'mode': str(mode), 'stage': str(stage), 'stage_label': str(stage_label), 'percent': safe_percent, 'processed_bytes': max(0, int(processed_bytes)), 'total_bytes': max(0, int(total_bytes)), 'processed_files': max(0, int(processed_files)), 'total_files': max(0, int(total_files)), 'speed_bps': max(0.0, round(float(speed_bps), 1)), 'elapsed_seconds': max(0, int(round(elapsed_seconds))), 'eta_seconds': safe_eta, 'estimated_finish_at': (now + timedelta(seconds=safe_eta)).isoformat(timespec='seconds') if safe_eta is not None else None, 'current_file': safe_current, 'archive_bytes': max(0, int(archive_bytes)), 'indeterminate': bool(indeterminate), 'updated_at': now.isoformat(timespec='seconds')}

    def start_operation(self, name: str, callback: Callable[[], Any]) -> None:
        self._reserve_operation(name)
        threading.Thread(target=lambda: self._execute_reserved_operation(name, callback, propagate=False), name=f'QiZhang-Operation-{name}', daemon=False).start()

    def _reserve_operation(self, name: str) -> None:
        with self._operation_lock:
            if getattr(self, '_native_exit_pending', False):
                raise PanelError('面板正在退出以安装更新，暂不接受新的服务器操作。')
            if self._operation.get('active'):
                raise PanelError(f'已有操作正在执行：{self._operation.get('name', '未知操作')}')
            self._set_operation(True, name, '正在执行…', True)

    def ensure_idle(self) -> None:
        with self._operation_lock:
            if getattr(self, '_native_exit_pending', False):
                raise PanelError('面板正在退出以安装更新，暂不接受新的服务器操作。')
            if self._operation.get('active'):
                raise PanelError(f'当前正在执行“{self._operation.get('name', '服务器操作')}”，请完成后再进行此操作。')

    def run_direct_mutation(self, callback: Callable[[], Any]) -> Any:
        self.ensure_idle()
        if not self._mutation_lock.acquire(blocking=False):
            raise PanelError('服务器正在处理另一项修改，请稍后再试；当前修改尚未执行。')
        try:
            self.ensure_idle()
            return callback()
        finally:
            self._mutation_lock.release()

    def _execute_reserved_operation(self, name: str, callback: Callable[[], Any], *, propagate: bool) -> Any:
        try:
            with self._mutation_lock:
                result = callback()
        except StartupCancelled as error:
            self._startup_waiting = False
            self.log(str(error))
            self._set_operation(False, name, str(error), True, True, cancelled=True)
            if propagate:
                raise
            return None
        except Exception as error:
            self._startup_waiting = False
            self.log(f'{name}失败：{error}', 'ERROR')
            self._set_operation(False, name, str(error), False, True)
            if propagate:
                raise
            return None
        self._set_operation(False, name, f'{name}已完成。', True, True)
        return result

    def run_operation_sync(self, name: str, callback: Callable[[], Any]) -> Any:
        self._reserve_operation(name)
        return self._execute_reserved_operation(name, callback, propagate=True)

    def request_server_action(self, action: str, *, backup_mode: str | None=None) -> str:
        action = str(action or '').strip().lower()
        names = {'start': '启动服务器', 'stop': '安全关闭服务器', 'restart': '重启服务器', 'save': '保存世界', 'backup': '创建备份', 'force_stop': '强制停止服务器'}
        if action not in names:
            raise PanelError('未知的服务器操作。')
        if action == 'stop':
            with self._operation_lock:
                if self._operation.get('active') and self._operation.get('name') in STARTUP_OPERATION_NAMES and self._startup_waiting and self._supports_startup_stop():
                    if self._startup_cancel_requested.is_set():
                        return '停止启动请求已接受，正在等待退出；未重复发送命令。'
                    owned = self._owned_startup_stop_target()
                    if owned is not None:
                        self._startup_stop_owned = owned
                        self._startup_cancel_requested.set()
                        self._operation['message'] = '启动中停止请求已排队，等待本次进程正常退出。'
                        return '停止启动请求已接受，正常停服完成后才结束本次操作。'
                    job = self._hidden_startup_job()
                    if job is not None:
                        self._startup_stop_job = job
                        self._startup_cancel_requested.set()
                        self._operation['message'] = '正在请求原启动器正常关闭，等待其子进程退出。'
                        return '关闭启动器请求已排队；确认全部进程退出后才解除启动状态。'
                    if not self._supports_supervisor_startup_stop():
                        raise PanelError('本次启动进程已退出或输入身份无法确认，未发送停服命令；请刷新状态。')
                    atomic_write_text(self.stop_flag_path, f'startup-stop-requested:{uuid.uuid4().hex}', 'ascii')
                    self._startup_cancel_requested.set()
                    self._operation['message'] = '启动中停止请求已排队，正在等待监督安全关闭本实例。'
                    return '停止请求已排队；监督和本实例子进程全部退出后才完成。'
            if self.starting_flag_path.exists() and (not self._status.get('ready')):
                owned = self._owned_startup_stop_target()
                if owned is not None:
                    self.start_operation(names[action], lambda: self._stop_owned_incomplete_startup(owned))
                    return '已请求正常停止尚未完成启动的进程；确认退出前保留启动标记。'
                job = self._hidden_startup_job()
                if job is not None:
                    self.start_operation(names[action], lambda: self._wait_for_hidden_startup_stop(job))
                    return '已请求正常关闭隐藏启动器；确认全部子进程退出前保留启动标记。'
        if action == 'start':
            self.reconcile_startup_state(force=True)
            self.start_operation(names[action], self.start_server)
        elif action == 'stop':
            self.start_operation(names[action], self.safe_stop_server)
        elif action == 'restart':
            self.start_operation(names[action], self.restart_server)
        elif action == 'save':
            self._require_platform_capability('save_world')
            self.start_operation(names[action], lambda: self.send_command('save-all flush'))
        elif action == 'backup':
            mode = self._normalise_backup_mode(backup_mode)
            operation_name = '创建停服轻量备份' if mode == 'light' else '创建完整备份'
            self.start_operation(operation_name, lambda: self.create_backup(mode=mode))
        else:
            self.start_operation(names[action], self.force_stop)
        if action == 'backup':
            return f'{operation_name}请求已接受。'
        return f'{names[action]}请求已接受。'

    @staticmethod
    def _normalize_server_bind(raw: Any) -> str:
        if not isinstance(raw, str):
            raise PanelError('服务器绑定地址必须是本机 IP；留空表示监听全部地址。')
        value = raw.strip()
        if not value:
            return ''
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise PanelError('服务器绑定地址只能填写本机 IPv4 / IPv6，或留空；不能填写域名、穿透地址或端口。') from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_multicast or str(address) == '255.255.255.255':
            raise PanelError('服务器绑定地址不能使用组播或广播地址。')
        return str(address)

    def requested_server_endpoint(self, properties: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a changed endpoint for the host's cross-instance check."""
        if not isinstance(properties, dict) or not {'server-ip', 'server-port'} & properties.keys():
            return None
        current = self.get_server_properties()
        address = self._normalize_server_bind(properties.get('server-ip', current.get('server-ip', '')))
        raw_port = properties.get('server-port', current.get('server-port', '25565'))
        if isinstance(raw_port, bool) or not re.fullmatch('[0-9]+', str(raw_port).strip()):
            raise PanelError('server-port 必须是整数。')
        port = int(str(raw_port).strip())
        if not 1 <= port <= 65535:
            raise PanelError('server-port 必须在 1～65535 之间。')
        try:
            current_port = int(current.get('server-port', '25565') or 25565)
            current_address = self._normalize_server_bind(current.get('server-ip', ''))
        except (ValueError, PanelError):
            current_port, current_address = (None, None)
        if address == current_address and port == current_port:
            return None
        return {'server-ip': address, 'server-port': port}

    def _server_endpoint_lock_reason(self, *, force: bool=False) -> str:
        """Call while holding operation/countdown locks; unknown is not offline."""
        if self._operation.get('active'):
            return '当前有服务器操作正在执行，请等待操作结束并关闭服务器。'
        if self._shutdown_countdown.get('active'):
            return '停服倒计时尚未结束，请等待服务器完全关闭。'
        if self.maintenance_flag_path.exists():
            return '服务器正在维护、备份或恢复，暂时不能修改地址和端口。'
        if self.starting_flag_path.exists() or self._startup_waiting:
            return '服务器仍在启动，请先停止启动并确认进程已退出。'
        launcher = self._startup_launcher
        if launcher is not None and launcher.poll() is None:
            return '服务器启动器仍在运行，请先完全关闭服务器。'
        try:
            if self.server_pid() or self._read_watchdog_pid(validate_command=True):
                return '服务器或守护进程仍在运行，地址和端口仅能在完全停服后修改。'
            activity = self._startup_process_snapshot(force=force)
        except (OSError, ValueError, PanelError):
            activity = None
        if activity is None:
            return '暂时无法确认服务器进程已全部退出，请刷新状态后再修改地址和端口。'
        if activity['java_pid'] or activity['launcher_pids'] or activity['watchdog_pids']:
            return '服务器、启动器或守护进程仍在运行，地址和端口仅能在完全停服后修改。'
        return ''

    @staticmethod
    def _check_server_endpoint_available(endpoint: dict[str, Any]) -> None:
        address, port = (endpoint['server-ip'], endpoint['server-port'])
        targets = [(socket.AF_INET6 if ':' in address else socket.AF_INET, address or '0.0.0.0')]
        if address == '::':
            targets = [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')]
        elif not address and socket.has_ipv6:
            targets.append((socket.AF_INET6, '::'))
        opened: list[socket.socket] = []
        try:
            for family, bind_address in targets:
                protocol = str(endpoint.get('network_protocol', 'TCP')).upper()
                if protocol not in {'TCP', 'UDP'}:
                    raise PanelError('未知的网络协议，无法确认端口。')
                listener = socket.socket(family, socket.SOCK_DGRAM if protocol == 'UDP' else socket.SOCK_STREAM)
                opened.append(listener)
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                if family == socket.AF_INET6:
                    listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                listener.bind((bind_address, port))
        except OSError as error:
            raise PanelError(f'无法使用绑定地址 {address or '全部本机地址'}、端口 {port}：地址必须属于本机，且端口不能已被其他程序占用。（系统错误 {(error.winerror if hasattr(error, 'winerror') else error.errno)}）') from error
        finally:
            for listener in opened:
                listener.close()

    def _update_properties(self, updates: dict[str, Any]) -> None:
        with self._shutdown_countdown_lock, self._operation_lock:
            allowed = self._platform_editable_properties()
            if set(updates) - set(allowed):
                raise PanelError('该平台不支持这些 Java 游戏服设置，未修改配置。')
            endpoint = self.requested_server_endpoint(updates)
            if endpoint is not None:
                endpoint['network_protocol'] = self.platform_profile()['network_protocol']
                reason = self._server_endpoint_lock_reason(force=True)
                if reason:
                    raise PanelError(reason)
                self._check_server_endpoint_available(endpoint)
            if self.platform_profile()['family'] == 'proxy':
                if endpoint is not None:
                    from native_platform_config import write_endpoint
                    write_endpoint(self.server_root, self.platform, endpoint['server-ip'], endpoint['server-port'])
                return
            self._update_properties_locked(updates, endpoint_changed=endpoint is not None)

    def _update_properties_locked(self, updates: dict[str, Any], *, endpoint_changed: bool) -> None:
        try:
            original = self.server_properties_path.read_bytes().decode('utf-8')
        except OSError as error:
            raise PanelError(f'无法读取 server.properties：{error}') from error
        rendered: dict[str, str] = {}
        for key, raw in updates.items():
            if key not in self.EDITABLE_PROPERTIES:
                continue
            kind, low, high = self.EDITABLE_PROPERTIES[key]
            if kind == 'str':
                value = str(raw).replace('\r', ' ').replace('\n', ' ')[:200]
            elif kind == 'ip':
                value = self._normalize_server_bind(raw)
            elif kind == 'bool':
                if isinstance(raw, bool):
                    value = 'true' if raw else 'false'
                elif isinstance(raw, str) and raw.lower() in {'true', 'false'}:
                    value = raw.lower()
                else:
                    raise PanelError(f'{key} 必须是布尔值。')
            elif kind == 'int':
                try:
                    number = int(raw)
                except (TypeError, ValueError):
                    raise PanelError(f'{key} 必须是整数。') from None
                if number < int(low) or number > int(high):
                    raise PanelError(f'{key} 必须在 {low}～{high} 之间。')
                value = str(number)
            else:
                value = str(raw).lower()
                if value not in low:
                    raise PanelError(f'{key} 的值无效。')
            rendered[key] = value
        if not rendered:
            return
        bom = '\ufeff' if original.startswith('\ufeff') else ''
        body = original[len(bom):]
        newline = '\r\n' if '\r\n' in body else '\n'
        found: set[str] = set()
        output: list[str] = []
        for logical, raw_record in self._property_records(body):
            if '=' in logical and (not logical.lstrip().startswith(('#', '!'))):
                key = logical.split('=', 1)[0].strip()
                if key in rendered:
                    found.add(key)
                    if logical.split('=', 1)[1] == rendered[key]:
                        output.append(raw_record)
                    else:
                        ending = raw_record[len(raw_record.rstrip('\r\n')):]
                        output.append(f'{key}={rendered[key]}{ending}')
                    continue
            output.append(raw_record)
        text = bom + ''.join(output)
        for key, value in rendered.items():
            if key not in found:
                tail_records = self._property_records(text[len(bom):])
                tail = tail_records[-1][0] if tail_records else ''
                if not tail.lstrip().startswith(('#', '!')) and (len(tail) - len(tail.rstrip('\\'))) % 2:
                    raise PanelError('server.properties 末尾存在未结束的续行，无法安全追加属性；原文件未修改。')
                if text and (not text.endswith(('\r', '\n', '\ufeff'))):
                    text += newline
                text += f'{key}={value}{newline}'
        if text == original:
            return
        if endpoint_changed:
            atomic_write_text(self.data_root / 'server-properties.before-endpoint-change.properties', original, 'utf-8')
        atomic_write_text(self.server_properties_path, text, 'utf-8')

    @staticmethod
    def _memory_to_mb(value: str) -> int:
        match = re.fullmatch('(\\d+)([MG])', value.upper())
        if not match:
            raise PanelError('内存格式应为数字加 M 或 G，例如 4G。')
        number = int(match.group(1))
        return number if match.group(2) == 'M' else number * 1024

    @staticmethod
    def _jvm_memory_tokens(text: str) -> list[tuple[str, str, int, int]]:
        """Locate whole heap arguments without rewriting other JVM tokens."""
        entries = []
        index = 0
        while index < len(text):
            if text[index].isspace() or (index == 0 and text[index] == '\ufeff'):
                index += 1
                continue
            if text[index] == '#':
                while index < len(text) and text[index] not in '\r\n':
                    index += 1
                continue
            start, quote, word = (index, '', [])
            while index < len(text):
                char = text[index]
                if not quote and (char.isspace() or char == '#'):
                    break
                if char in '"\'':
                    if not quote:
                        quote = char
                    elif quote == char:
                        quote = ''
                    else:
                        word.append(char)
                elif quote and char == '\\' and (index + 1 < len(text)):
                    word.extend((char, text[index + 1]))
                    index += 1
                else:
                    word.append(char)
                index += 1
            if quote:
                raise PanelError('JVM 参数文件引号未闭合，请在启动参数页面检查。')
            token = ''.join(word)
            if token.startswith(('-Xms', '-Xmx')):
                entries.append((token[1:4].lower(), token[4:], start, index))
        return entries

    def _get_jvm_memory(self) -> dict[str, str]:
        result = {'xms': '', 'xmx': ''}
        try:
            text = self.jvm_args_path.read_bytes().decode('utf-8')
        except FileNotFoundError:
            return result
        for key, value, _, _ in self._jvm_memory_tokens(text):
            result[key] = value
        return result

    def _update_jvm_memory(self, values: dict[str, Any]) -> None:
        if not isinstance(values, dict) or set(values) - {'xms', 'xmx'}:
            raise PanelError('Java 内存设置只能包含 xms / xmx。')
        if not values:
            return
        original = self.jvm_args_path.read_bytes().decode('utf-8') if self.jvm_args_path.exists() else ''
        entries = self._jvm_memory_tokens(original)
        current = {'xms': '', 'xmx': ''}
        for key, value, _, _ in entries:
            current[key] = value

        def memory_bytes(value):
            match = re.fullmatch('([0-9]+)([KMG]?)', value, re.I)
            if not match:
                raise PanelError('内存请填写整数字节或带 K/M/G 单位的整数，例如 512M、4G；留空由 Java 自动分配。')
            return int(match[1]) * {'': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3}[match[2].upper()]
        changed = {}
        for key, value in values.items():
            if not isinstance(value, str):
                raise PanelError('Java 内存必须是文本，不能将小数或未知单位自动换算。')
            value = value.strip()
            if value == current[key]:
                continue
            if value and (not 64 * 1024 ** 2 <= memory_bytes(value) <= 32 * 1024 ** 3):
                raise PanelError('手动设置的每项内存应在 64MB～32GB 之间；留空由 Java 自动分配。')
            changed[key] = value
        if not changed:
            return
        resulting = {**current, **changed}
        if resulting['xms'] and resulting['xmx'] and (memory_bytes(resulting['xms']) > memory_bytes(resulting['xmx'])):
            raise PanelError('最小内存不能大于最大内存。')
        last = {key: start for key, _, start, _ in entries}
        text = original
        for key, _, start, end in reversed(entries):
            if key in changed:
                value = changed[key]
                replacement = '-X' + key[1:] + value if value and start == last[key] else ''
                text = text[:start] + replacement + text[end:]
        newline = '\r\n' if '\r\n' in original else '\n'
        for key, value in changed.items():
            if value and key not in last:
                if text and (not text.endswith(('\r', '\n', '\ufeff'))):
                    text += newline
                text += '-X' + key[1:] + value + newline
        if text != original:
            atomic_write_text(self.jvm_args_path, text, 'utf-8')

    def get_settings(self) -> dict[str, Any]:
        properties = self.get_server_properties()
        spec = self.platform_profile()
        allowed = self._platform_editable_properties()
        spec['editable_properties'] = allowed
        editable = {key: properties[key] for key in allowed if key in properties}
        for key, (kind, _, _) in self.EDITABLE_PROPERTIES.items():
            if key not in editable:
                continue
            if kind == 'bool' and str(editable[key]).lower() in {'true', 'false'}:
                editable[key] = str(editable[key]).lower() == 'true'
            elif kind == 'int':
                try:
                    editable[key] = int(editable[key])
                except (TypeError, ValueError):
                    pass
        for key, choices in {'gamemode': ('survival', 'creative', 'adventure', 'spectator'), 'difficulty': ('peaceful', 'easy', 'normal', 'hard')}.items():
            value = editable.get(key)
            if isinstance(value, str) and value in {'0', '1', '2', '3'}:
                editable[key] = choices[int(value)]
        with self._config_lock:
            panel = {'poll_seconds': self.config.get('poll_seconds', 2)}
            gamerules = dict(self.config.get('gamerules', {}))
        with self._shutdown_countdown_lock, self._operation_lock:
            endpoint_lock_reason = self._server_endpoint_lock_reason()
        return {'server_properties': editable, 'server_properties_present': sorted(editable), 'editable_properties': allowed, 'platform_profile': spec, 'jvm': self._get_jvm_memory() if spec['capabilities']['java'] else {}, 'gamerules': gamerules if spec['family'] == 'java' else {}, 'panel': panel, 'capabilities': {**spec['capabilities'], 'watchdog': self.supports_watchdog, 'control_script': bool(self.control_script), 'server_endpoint_editable': not endpoint_lock_reason, 'server_endpoint_lock_reason': endpoint_lock_reason}, 'restart_required': False}

    def update_settings(self, payload: dict[str, Any]) -> str:
        with self._mutation_lock:
            return self._update_settings_locked(payload)

    def _update_settings_locked(self, payload):
        if not isinstance(payload, dict):
            raise PanelError('设置格式无效。')
        panel = payload.get('panel', {})
        if not isinstance(panel, dict) or set(panel) - {'poll_seconds'}:
            raise PanelError('仅支持基础服务器设置和刷新间隔。')
        if payload.get('jvm'):
            self._require_platform_capability('java')
        if payload.get('gamerules') and self.platform_profile()['family'] != 'java':
            raise PanelError('该平台没有 Java 游戏规则设置，未修改配置。')
        properties = payload.get('server_properties', {})
        if isinstance(properties, dict) and properties:
            self._update_properties(properties)
        jvm = payload.get('jvm', {})
        if isinstance(jvm, dict) and jvm:
            self._update_jvm_memory(jvm)
        rules = payload.get('gamerules', {})
        if isinstance(rules, dict) and rules:
            updates = {}
            if 'keepInventory' in rules:
                updates['keepInventory'] = bool(rules['keepInventory'])
            if 'playersSleepingPercentage' in rules:
                value = int(rules['playersSleepingPercentage'])
                if not 0 <= value <= 100:
                    raise PanelError('睡眠跳夜比例必须在 0～100 之间。')
                updates['playersSleepingPercentage'] = value
            with self._config_lock:
                self.config.setdefault('gamerules', {}).update(updates)
            if self.server_pid():
                for key, value in updates.items():
                    rendered = str(value).lower() if isinstance(value, bool) else value
                    self.send_command(f'gamerule {key} {rendered}')
        if 'poll_seconds' in panel:
            poll = int(panel['poll_seconds'])
            if not 1 <= poll <= 30:
                raise PanelError('刷新间隔必须在 1～30 秒之间。')
            with self._config_lock:
                self.config['poll_seconds'] = poll
        self.save_panel_config()
        self.log('基础设置已更新。')
        return '设置已保存；服务端属性和内存改动将在下次启动后完全生效。'

    def set_panel_autostart(self, enabled: bool) -> None:
        appdata = os.environ.get('APPDATA')
        if not appdata:
            raise PanelError('无法定位 Windows 启动文件夹。')
        startup = Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
        startup.mkdir(parents=True, exist_ok=True)
        entry = startup / 'QiZhangServerPanel.cmd'
        if enabled:
            launcher = self.panel_root / '启动七章服务器管理面板.bat'
            content = f'@echo off\r\nstart "" /min "{launcher}" --autostart\r\n'
            last_error: OSError | None = None
            for attempt in range(4):
                try:
                    entry.write_text(content, encoding='utf-8', newline='')
                    last_error = None
                    break
                except OSError as error:
                    last_error = error
                    time.sleep(0.2 * (attempt + 1))
            if last_error is not None:
                raise PanelError(f'无法写入 Windows 开机启动项：{last_error}') from last_error
        else:
            try:
                entry.unlink(missing_ok=True)
            except OSError as error:
                raise PanelError(f'无法移除开机启动项：{error}') from error

    def _wait_process_exit(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while pid > 0 and self.process_exists(pid):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)
        return True

    def _normalise_backup_mode(self, mode: str | None=None) -> str:
        if mode is None and (self.platform_profile()['family'] != 'java'):
            return 'full'
        if mode is None:
            with self._config_lock:
                mode = str(self.config.get('backup_mode', 'light'))
        mode = str(mode or '').strip().lower()
        aliases = {'cold': 'full', 'shutdown': 'full'}
        mode = aliases.get(mode, mode)
        if mode not in BACKUP_MODES:
            raise PanelError('备份方式只能是停服轻量备份或停服完整备份。')
        return mode

    def _iter_light_backup_files(self, source_root: Path | None=None) -> list[Path]:
        base = Path(source_root) if source_root is not None else self.server_root
        worlds = [base / name for name in self._java_world_layout(base)['worlds']]
        files: set[Path] = set()
        directory_roots = [base / 'config', base / 'defaultconfigs']
        directory_roots.extend((world / name for world in worlds for name in ('playerdata', 'advancements', 'stats', 'ftbquests', 'ftbteams', 'serverconfig', 'datapacks')))
        for root in directory_roots:
            self._reject_backup_link(root)
            if not root.is_dir():
                continue
            for item in root.rglob('*'):
                self._reject_backup_link(item)
                if item.is_file():
                    files.add(item)
        direct_files = ('server.properties', 'ops.json', 'whitelist.json', 'banned-players.json', 'banned-ips.json', 'usercache.json', 'user_jvm_args.txt')
        direct_paths = [base / relative for relative in direct_files]
        direct_paths.extend((world / name for world in worlds for name in ('level.dat', 'level.dat_old', 'mfix_stronghold_cache_v2.nbt')))
        for item in direct_paths:
            self._reject_backup_link(item)
            if item.is_file():
                files.add(item)
        for world in worlds:
            if not world.is_dir():
                continue
            for item in world.rglob('*'):
                self._reject_backup_link(item)
                if not item.is_file():
                    continue
                relative = item.relative_to(world)
                if 'data' not in relative.parts[:-1]:
                    continue
                if 'lootr' in relative.parts:
                    continue
                if LIGHT_BACKUP_EXCLUDED_NAMES.fullmatch(item.name):
                    continue
                files.add(item)
        return sorted(files, key=lambda item: str(item).lower())

    def _stage_light_backup(self, staging: Path) -> list[str]:
        copied: list[str] = []
        layout = self._java_world_layout()
        for source in self._iter_light_backup_files():
            try:
                relative = source.relative_to(self.server_root)
            except ValueError as error:
                raise PanelError(f'轻量备份路径越界：{source}') from error
            if self._world_chunk_path(relative, layout):
                raise PanelError(f'轻量备份意外包含地图文件：{relative}')
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            last_error: OSError | None = None
            for attempt in range(3):
                try:
                    shutil.copy2(source, destination)
                    last_error = None
                    break
                except OSError as error:
                    last_error = error
                    time.sleep(0.1 * (attempt + 1))
            if last_error is not None:
                raise PanelError(f'复制轻量备份文件失败：{relative}：{last_error}') from last_error
            copied.append(relative.as_posix())
        if not (staging / layout['primary'] / 'level.dat').is_file():
            raise PanelError('世界目录缺少 level.dat，轻量备份已取消。')
        return copied

    def create_light_backup(self) -> Path:
        self._require_stopped_for_backup()
        if self.platform_profile()['family'] != 'java':
            raise PanelError('轻量备份仅支持 Java 游戏服务器。')
        self.ensure_not_starting()
        backup_root = self.server_root / 'backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        destination = backup_root / f'panel_light_{stamp}.zip'
        partial = backup_root / f'panel_light_{stamp}.partial'
        staging = Path(tempfile.mkdtemp(prefix='.light-staging-', dir=backup_root)).resolve()
        server_pid = self.validated_server_pid()
        copied_files: list[str] = []
        try:
            copied_files = self._stage_light_backup(staging)
            manifest = {'format': 2, 'mode': 'light', 'world_layout': self._java_world_layout(), 'contains_world_chunks': False, 'server_id': self.server_id, 'created_at': datetime.now().isoformat(timespec='seconds'), 'source_server_running': bool(server_pid), 'files': copied_files, 'excluded': ['区块、实体、兴趣点与各维度地形文件', 'DistantHorizons.sqlite*', 'map_*.dat', 'ae2_compass_*.dat', '各世界目录/data/lootr/**（地图战利品箱记录）']}
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
                for relative in copied_files:
                    source = staging / Path(relative)
                    if source.is_file():
                        archive.write(source, relative)
                archive.writestr('qizhang-backup-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            with zipfile.ZipFile(partial, 'r') as verification:
                damaged = verification.testzip()
                if damaged:
                    raise PanelError(f'轻量备份校验失败，损坏文件：{damaged}')
            os.replace(partial, destination)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        keep = int(self.config.get('light_backup_keep', 3))
        backups = sorted(backup_root.glob('panel_light_*.zip'), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            try:
                old.unlink()
                self.log(f'已自动清理旧轻量备份：{old.name}')
            except OSError as error:
                self.log(f'清理旧轻量备份失败：{old.name}：{error}', 'WARN')
        self.log(f'停服轻量备份已完成：{destination.name}，{len(copied_files)} 个文件。')
        return destination

    def create_backup(self, mode: str | None=None) -> Path:
        mode = self._normalise_backup_mode(mode)
        if mode == 'light':
            return self.create_light_backup()
        return self._create_full_backup()

    @staticmethod
    def _java_property_unescape(value: str) -> str:
        result = []
        index = 0
        while index < len(value):
            char = value[index]
            index += 1
            if char != '\\':
                result.append(char)
                continue
            if index >= len(value):
                raise PanelError('世界名称属性包含未结束的转义，备份已取消。')
            char = value[index]
            index += 1
            if char == 'u':
                digits = value[index:index + 4]
                if not re.fullmatch('[0-9a-fA-F]{4}', digits):
                    raise PanelError('世界名称属性的 Unicode 转义无效，备份已取消。')
                result.append(chr(int(digits, 16)))
                index += 4
            else:
                result.append({'t': '\t', 'r': '\r', 'n': '\n', 'f': '\x0c'}.get(char, char))
        try:
            return ''.join(result).encode('utf-16-le', 'surrogatepass').decode('utf-16-le')
        except UnicodeError as error:
            raise PanelError('世界名称属性含不完整 Unicode 字符，备份已取消。') from error

    def _java_world_layout(self, source_root: Path | None=None) -> dict[str, Any]:
        base = (Path(source_root) if source_root is not None else self.server_root).resolve()
        properties = base / 'server.properties'
        name = 'world'
        if properties.exists():
            self._reject_backup_link(properties)
            with properties.open('rb') as source:
                raw = source.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise PanelError('server.properties 过大，无法安全确定备份世界目录。')
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('iso-8859-1')
            for logical, _ in self._property_records(text):
                line = logical.lstrip(' \t\x0c')
                if not line or line[0] in '#!':
                    continue
                end = 0
                while end < len(line):
                    if line[end] == '\\':
                        end += 2
                    elif line[end] in '=: \t\x0c':
                        break
                    else:
                        end += 1
                key = line[:end]
                if key != 'level-name' and '\\' not in key:
                    continue
                if self._java_property_unescape(key) != 'level-name':
                    continue
                value = line[end:].lstrip(' \t\x0c')
                if value[:1] in {'=', ':'}:
                    value = value[1:].lstrip(' \t\x0c')
                name = self._java_property_unescape(value)
        name = name.replace('\\', '/')
        parts = name.split('/')
        reserved = {'backups', 'logs', 'config', 'defaultconfigs', 'plugins', 'mods', 'libraries', 'runtime', 'qizhang-tools'}
        if not name or PureWindowsPath(name).is_absolute() or PureWindowsPath(name).drive or name.startswith('/') or any((part in {'', '.', '..'} for part in parts)) or any((char in ':*?"<>|' or ord(char) < 32 for char in name)) or any((part.endswith(('.', ' ')) for part in parts)) or (parts[0].casefold() in reserved) or parts[0].lower().startswith('.qizhang'):
            raise PanelError('无法安全备份或恢复此世界路径；请核对路径或使用独立离线备份，现有文件未修改。')
        primary = Path(*parts)
        candidates = [primary, primary.with_name(primary.name + '_nether'), primary.with_name(primary.name + '_the_end')]
        worlds = []
        for relative in candidates:
            path = base / relative
            self._reject_backup_link(path)
            if not path.resolve().is_relative_to(base) or path.resolve() == base:
                raise PanelError('世界目录越出服务端根目录，备份/恢复已取消。')
            if path.exists() and (not path.is_dir()):
                raise PanelError('世界路径不是文件夹，备份/恢复已取消。')
            if relative == primary or path.is_dir():
                worlds.append(relative.as_posix())
        return {'schema': 1, 'primary': primary.as_posix(), 'worlds': worlds}

    @staticmethod
    def _world_chunk_path(relative: Path, layout: dict[str, Any]) -> bool:
        for name in layout['worlds']:
            root = Path(name)
            if relative.is_relative_to(root) and any((part in {'region', 'entities', 'poi'} for part in relative.relative_to(root).parts)):
                return True
        return False

    def _java_restore_layout(self, staging: Path) -> dict[str, Any]:
        incoming = self._java_world_layout(staging)
        current = self._java_world_layout()
        if incoming['primary'] != current['primary']:
            raise PanelError('备份与当前 level-name 指向不同世界目录，已取消自动恢复，现有文件未覆盖。')
        if not (staging / incoming['primary'] / 'level.dat').is_file():
            raise PanelError('备份不包含已声明世界目录的 level.dat，不能用于一键恢复。')
        manifest_path = staging / 'qizhang-backup-manifest.json'
        if manifest_path.is_file():
            if manifest_path.stat().st_size > 32 * 1024 * 1024:
                raise PanelError('备份清单过大，已取消自动恢复。')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            declared = manifest.get('world_layout')
            if declared is not None and declared != incoming:
                raise PanelError('备份世界清单与归档配置或实际世界目录不一致，已取消自动恢复。')
        if set(current['worlds']) - set(incoming['worlds']):
            raise PanelError('备份未包含当前服务器的全部标准维度目录，已取消恢复以免混用不同时间的世界。')
        for name in incoming['worlds']:
            self._reject_backup_link(self.server_root / name)
        return incoming

    def _platform_backup_items(self):
        spec = self.platform_profile()
        if spec['family'] == 'java':
            return None
        if spec['family'] == 'custom':
            raise PanelError('自定义平台未定义备份布局，请使用外部离线备份。')
        return tuple(dict.fromkeys((spec['config_file'], 'worlds', 'plugins', 'config', 'ops.txt', 'ops.json', 'permissions.yml', 'whitelist.json', 'white-list.txt', 'banned-players.json', 'banned-ips.json', 'pocketmine.yml', 'nukkit.yml', 'permissions.json', 'allowlist.json', 'resource_packs', 'behavior_packs')))

    def _reject_backup_link(self, path):
        for candidate in (path, *path.parents):
            if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
                raise PanelError('备份路径含符号链接或目录联接，已拒绝读取外部目录。')
            if candidate == self.server_root:
                break

    def _create_full_backup(self) -> Path:
        self._require_stopped_for_backup()
        self.ensure_not_starting()
        backup_started = time.monotonic()
        backup_root = self.server_root / 'backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        destination = backup_root / f'panel_world_{stamp}.zip'
        partial = backup_root / f'panel_world_{stamp}.partial'
        original_pid = self.validated_server_pid()
        server_was_running = False
        world_layout = self._java_world_layout() if self.platform_profile()['family'] == 'java' else None
        roots = [self.server_root / 'server.properties', self.server_root / 'config', self.server_root / 'defaultconfigs', self.server_root / 'ops.json', self.server_root / 'whitelist.json', self.server_root / 'banned-players.json', self.server_root / 'banned-ips.json', self.server_root / 'usercache.json', self.server_root / 'user_jvm_args.txt']
        platform_items = self._platform_backup_items()
        if platform_items is not None:
            roots = [self.server_root / name for name in platform_items]
        else:
            roots[:0] = [self.server_root / name for name in world_layout['worlds']]
        maintenance_owned = False
        backup_error: Exception | None = None
        world_size = 0
        backup_files: list[tuple[Path, str, int]] = []
        restore_estimate_seconds = 75 if server_was_running else 2
        try:
            if not self.maintenance_flag_path.exists():
                self.maintenance_flag_path.write_text('backup', encoding='ascii')
                maintenance_owned = True
            if platform_items is not None:
                activity = self._startup_process_snapshot(force=True)
                if activity is None or activity['java_pid'] or activity['launcher_pids'] or activity['watchdog_pids']:
                    raise PanelError('无法确认平台服务端已全部退出，离线备份已取消。')
            world_root = self.server_root / world_layout['primary'] if world_layout else None
            if platform_items is None and (not (world_root / 'level.dat').is_file()):
                raise PanelError('世界目录缺少 level.dat，备份已取消。')
            self._set_operation_progress(mode='full', stage='scanning', stage_label='正在统计备份文件', percent=2.0, elapsed_seconds=time.monotonic() - backup_started, indeterminate=True)
            scan_last_update = 0.0
            for root in roots:
                if not root.exists():
                    continue
                self._reject_backup_link(root)
                candidates = [root] if root.is_file() else root.rglob('*')
                for item in candidates:
                    self._reject_backup_link(item)
                    if not item.is_file() or item.name == 'session.lock':
                        continue
                    try:
                        size = item.stat().st_size
                        relative = item.relative_to(self.server_root).as_posix()
                    except (OSError, ValueError) as error:
                        raise PanelError(f'统计备份文件失败：{item}：{error}') from error
                    backup_files.append((item, relative, size))
                    world_size += size
                    now_monotonic = time.monotonic()
                    if now_monotonic - scan_last_update >= 0.5:
                        self._set_operation_progress(mode='full', stage='scanning', stage_label='正在统计备份文件', percent=2.0, elapsed_seconds=now_monotonic - backup_started, processed_bytes=world_size, processed_files=len(backup_files), current_file=relative, indeterminate=True)
                        scan_last_update = now_monotonic
            if not backup_files:
                raise PanelError('完整备份文件清单为空，备份已取消。')
            total_files = len(backup_files)
            total_bytes = world_size
            free_space = shutil.disk_usage(backup_root).free
            required_space = max(5 * 1024 ** 3, int(total_bytes * 0.35))
            if free_space < required_space:
                raise PanelError(f'备份磁盘空间不足：至少需要约 {required_space / 1024 ** 3:.1f}GB 可用空间。')
            compression_started = time.monotonic()
            compressed_bytes = 0
            compressed_files = 0
            compression_last_update = 0.0
            self._set_operation_progress(mode='full', stage='compressing', stage_label='正在压缩完整备份', percent=5.0, elapsed_seconds=compression_started - backup_started, total_bytes=total_bytes, total_files=total_files)
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
                for item, relative, size in backup_files:
                    try:
                        zip_info = zipfile.ZipInfo.from_file(item, relative)
                        zip_info.compress_type = archive.compression
                        zip_info._compresslevel = archive.compresslevel
                        with item.open('rb') as source, archive.open(zip_info, 'w', force_zip64=True) as target:
                            while True:
                                chunk = source.read(4 * 1024 * 1024)
                                if not chunk:
                                    break
                                target.write(chunk)
                                compressed_bytes += len(chunk)
                                now_monotonic = time.monotonic()
                                if now_monotonic - compression_last_update < 0.35:
                                    continue
                                phase_elapsed = max(0.001, now_monotonic - compression_started)
                                speed = compressed_bytes / phase_elapsed
                                ratio = compressed_bytes / max(1, total_bytes)
                                eta = (max(0, total_bytes - compressed_bytes) + total_bytes) / speed + restore_estimate_seconds if speed > 0 else None
                                archive_size = 0
                                try:
                                    archive_size = partial.stat().st_size
                                except OSError:
                                    pass
                                self._set_operation_progress(mode='full', stage='compressing', stage_label='正在压缩完整备份', percent=5.0 + ratio * 70.0, elapsed_seconds=now_monotonic - backup_started, processed_bytes=compressed_bytes, total_bytes=total_bytes, processed_files=compressed_files, total_files=total_files, speed_bps=speed, eta_seconds=eta, current_file=relative, archive_bytes=archive_size)
                                compression_last_update = now_monotonic
                    except (OSError, PermissionError, RuntimeError) as error:
                        raise PanelError(f'备份文件失败，未生成不完整备份：{item}：{error}') from error
                    compressed_files += 1
                    now_monotonic = time.monotonic()
                    if now_monotonic - compression_last_update >= 0.35 or compressed_files == total_files:
                        phase_elapsed = max(0.001, now_monotonic - compression_started)
                        speed = compressed_bytes / phase_elapsed
                        ratio = compressed_bytes / max(1, total_bytes)
                        eta = (max(0, total_bytes - compressed_bytes) + total_bytes) / speed + restore_estimate_seconds if speed > 0 else None
                        archive_size = 0
                        try:
                            archive_size = partial.stat().st_size
                        except OSError:
                            pass
                        self._set_operation_progress(mode='full', stage='compressing', stage_label='正在压缩完整备份', percent=5.0 + ratio * 70.0, elapsed_seconds=now_monotonic - backup_started, processed_bytes=compressed_bytes, total_bytes=total_bytes, processed_files=compressed_files, total_files=total_files, speed_bps=speed, eta_seconds=eta, current_file=relative, archive_bytes=archive_size)
                        compression_last_update = now_monotonic
                if world_layout is not None:
                    archive.writestr('qizhang-backup-manifest.json', json.dumps({'format': 3, 'mode': 'full', 'world_layout': world_layout}, ensure_ascii=False, indent=2) + '\n')
            verification_started = time.monotonic()
            verified_bytes = 0
            verified_files = 0
            verification_last_update = 0.0
            self._set_operation_progress(mode='full', stage='verifying', stage_label='正在校验完整备份', percent=75.0, elapsed_seconds=verification_started - backup_started, total_bytes=total_bytes, total_files=total_files, archive_bytes=partial.stat().st_size)
            with zipfile.ZipFile(partial, 'r') as verification:
                members = [item for item in verification.infolist() if not item.is_dir() and (world_layout is None or item.filename != 'qizhang-backup-manifest.json')]
                if world_layout is not None:
                    metadata = json.loads(verification.read('qizhang-backup-manifest.json'))
                    if metadata.get('world_layout') != world_layout:
                        raise PanelError('备份世界布局清单校验失败。')
                if len(members) != total_files:
                    raise PanelError(f'备份校验失败：压缩包文件数量与源清单不一致，源={total_files}，压缩包={len(members)}。')
                verification_total = sum((item.file_size for item in members))
                if verification_total != total_bytes:
                    raise PanelError(f'备份校验失败：压缩包数据量与源清单不一致，源={total_bytes}，压缩包={verification_total}。')
                for member in members:
                    try:
                        with verification.open(member, 'r') as source:
                            while True:
                                chunk = source.read(4 * 1024 * 1024)
                                if not chunk:
                                    break
                                verified_bytes += len(chunk)
                                now_monotonic = time.monotonic()
                                if now_monotonic - verification_last_update >= 0.35:
                                    phase_elapsed = max(0.001, now_monotonic - verification_started)
                                    speed = verified_bytes / phase_elapsed
                                    ratio = verified_bytes / max(1, total_bytes)
                                    eta = max(0, total_bytes - verified_bytes) / speed + restore_estimate_seconds if speed > 0 else None
                                    self._set_operation_progress(mode='full', stage='verifying', stage_label='正在校验完整备份', percent=75.0 + ratio * 23.0, elapsed_seconds=now_monotonic - backup_started, processed_bytes=verified_bytes, total_bytes=total_bytes, processed_files=verified_files, total_files=total_files, speed_bps=speed, eta_seconds=eta, current_file=member.filename, archive_bytes=partial.stat().st_size)
                                    verification_last_update = now_monotonic
                    except (OSError, EOFError, zipfile.BadZipFile) as error:
                        raise PanelError(f'备份校验失败，损坏文件：{member.filename}：{error}') from error
                    verified_files += 1
                verify_elapsed = max(0.001, time.monotonic() - verification_started)
                self._set_operation_progress(mode='full', stage='verifying', stage_label='正在校验完整备份', percent=98.0, elapsed_seconds=time.monotonic() - backup_started, processed_bytes=verified_bytes, total_bytes=total_bytes, processed_files=verified_files, total_files=total_files, speed_bps=verified_bytes / verify_elapsed, eta_seconds=restore_estimate_seconds, archive_bytes=partial.stat().st_size)
            self._set_operation_progress(mode='full', stage='finalizing', stage_label='正在完成备份文件', percent=98.5, elapsed_seconds=time.monotonic() - backup_started, processed_bytes=total_bytes, total_bytes=total_bytes, processed_files=total_files, total_files=total_files, eta_seconds=restore_estimate_seconds, archive_bytes=partial.stat().st_size)
            os.replace(partial, destination)
        except Exception as error:
            backup_error = error
            partial.unlink(missing_ok=True)
            raise
        finally:
            if maintenance_owned:
                self.maintenance_flag_path.unlink(missing_ok=True)
        self._set_operation_progress(mode='full', stage='cleanup', stage_label='正在清理旧备份', percent=99.5, elapsed_seconds=time.monotonic() - backup_started, processed_bytes=world_size, total_bytes=world_size, processed_files=len(backup_files), total_files=len(backup_files), eta_seconds=1, archive_bytes=destination.stat().st_size)
        keep = int(self.config.get('backup_keep', 7))
        backups = sorted((item for item in backup_root.glob('*.zip') if not item.name.startswith('panel_light_')), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
        self.log(f'备份已完成：{destination.name}')
        return destination

    def list_backups(self) -> list[dict[str, Any]]:
        backup_root = self.server_root / 'backups'
        result: list[dict[str, Any]] = []
        if not backup_root.exists():
            return result
        for item in backup_root.glob('*.zip'):
            try:
                stat = item.stat()
            except OSError:
                continue
            result.append({'name': item.name, 'size': stat.st_size, 'size_mb': round(stat.st_size / (1024 * 1024), 1), 'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'), 'mode': 'light' if item.name.startswith('panel_light_') else 'full'})
        result.sort(key=lambda item: item['modified'], reverse=True)
        return result

    def delete_backup(self, filename: str) -> None:
        if not filename or Path(filename).name != filename or (not filename.lower().endswith('.zip')):
            raise PanelError('备份文件名无效。')
        root = (self.server_root / 'backups').resolve()
        target = (root / filename).resolve()
        if target.parent != root:
            raise PanelError('拒绝访问备份目录之外的文件。')
        if not target.is_file():
            raise PanelError('备份文件不存在。')
        target.unlink()
        self.log(f'已删除备份：{filename}', 'WARN')

    def _validated_backup_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename or (not filename.lower().endswith('.zip')):
            raise PanelError('备份文件名无效。')
        root = (self.server_root / 'backups').resolve()
        target = (root / filename).resolve()
        if target.parent != root or not target.is_file():
            raise PanelError('备份文件不存在或不在备份目录中。')
        return target

    @staticmethod
    def _safe_extract_backup(archive_path: Path, destination: Path) -> None:
        destination_resolved = destination.resolve()
        with zipfile.ZipFile(archive_path, 'r') as archive:
            damaged = archive.testzip()
            if damaged:
                raise PanelError(f'备份压缩包校验失败，损坏文件：{damaged}')
            members = archive.infolist()
            if not members:
                raise PanelError('备份压缩包为空。')
            total_size = sum((max(0, item.file_size) for item in members))
            if total_size > 500 * 1024 * 1024 * 1024:
                raise PanelError('备份解压后超过 500GB，拒绝恢复。')
            free_space = shutil.disk_usage(destination_resolved).free
            required_space = int(total_size * 1.1) + 1024 ** 3
            if free_space < required_space:
                raise PanelError(f'恢复暂存空间不足：至少需要约 {required_space / 1024 ** 3:.1f}GB 可用空间。')
            for member in members:
                name = member.filename.replace('\\', '/')
                path = Path(name)
                if not name or path.is_absolute() or '..' in path.parts or (path.parts and ':' in path.parts[0]):
                    raise PanelError(f'备份中包含不安全路径：{member.filename}')
                target = (destination_resolved / path).resolve()
                if target != destination_resolved and destination_resolved not in target.parents:
                    raise PanelError(f'备份路径越界：{member.filename}')
            archive.extractall(destination_resolved)

    @staticmethod
    def _backup_archive_mode(archive_path: Path) -> str:
        try:
            with zipfile.ZipFile(archive_path, 'r') as archive:
                raw = archive.read('qizhang-backup-manifest.json')
            manifest = json.loads(raw.decode('utf-8-sig'))
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            return 'full'
        mode = str(manifest.get('mode', 'full')).strip().lower()
        return 'light' if mode == 'light' else 'full'

    def _restore_light_backup(self, target: Path, filename: str, restart_after: bool) -> None:
        self._require_stopped_for_backup()
        original_pid = self.validated_server_pid()
        server_was_running = False
        backup_root = (self.server_root / 'backups').resolve()
        staging = Path(tempfile.mkdtemp(prefix='.light-restore-staging-', dir=backup_root)).resolve()
        rollback = (backup_root / f'.light-restore-rollback-{uuid.uuid4().hex[:10]}').resolve()
        rollback.mkdir(parents=True, exist_ok=False)
        moved_old: list[str] = []
        installed_new: list[str] = []
        maintenance_owned = False
        shutdown_started = False
        committed = False
        rollback_ok = True
        failure: Exception | None = None
        try:
            self._safe_extract_backup(target, staging)
            manifest_path = staging / 'qizhang-backup-manifest.json'
            if not manifest_path.is_file():
                raise PanelError('轻量备份缺少清单文件，拒绝自动恢复。')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            if manifest.get('mode') != 'light':
                raise PanelError('备份类型与轻量恢复流程不匹配。')
            world_layout = self._java_restore_layout(staging)
            allowed_files = {item.relative_to(staging).as_posix() for item in self._iter_light_backup_files(staging)}
            raw_files = manifest.get('files')
            if not isinstance(raw_files, list) or not raw_files:
                raise PanelError('轻量备份文件清单为空。')
            incoming_files: list[str] = []
            for value in raw_files:
                relative = Path(str(value))
                if relative.is_absolute() or '..' in relative.parts or (not (staging / relative).is_file()):
                    raise PanelError(f'轻量备份清单包含无效路径：{value}')
                if self._world_chunk_path(relative, world_layout):
                    raise PanelError(f'轻量备份意外包含地图路径：{value}')
                if relative.as_posix() not in allowed_files or relative.as_posix() in incoming_files:
                    raise PanelError('轻量备份清单与允许恢复的地图元数据/配置范围不一致。')
                incoming_files.append(relative.as_posix())
            if world_layout['primary'] + '/level.dat' not in incoming_files:
                raise PanelError('轻量备份清单缺少主世界 level.dat。')
            current_pid = self.validated_server_pid()
            if current_pid != original_pid:
                raise PanelError('校验轻量备份期间服务器运行状态发生变化，请稍后再试。')
            self.ensure_not_starting()
            if self.maintenance_flag_path.exists():
                raise PanelError('检测到未结束的维护标记，请先确认上一次操作状态。')
            self.maintenance_flag_path.write_text('light-restore', encoding='ascii')
            maintenance_owned = True
            self.stop_flag_path.write_text('panel-light-restore', encoding='ascii')
            time.sleep(0.5)
            if self.validated_server_pid():
                raise PanelError('检测到服务器重新启动，恢复已取消。')
            safety_backup = self.create_light_backup()
            self.log(f'轻量恢复前安全备份已创建：{safety_backup.name}')
            current_files = {item.relative_to(self.server_root).as_posix() for item in self._iter_light_backup_files()}
            for relative_text in sorted(current_files):
                current = self.server_root / Path(relative_text)
                if not current.is_file():
                    continue
                saved = rollback / Path(relative_text)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current), str(saved))
                moved_old.append(relative_text)
            for relative_text in incoming_files:
                incoming = staging / Path(relative_text)
                current = self.server_root / Path(relative_text)
                current.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(incoming), str(current))
                installed_new.append(relative_text)
            self.log(f'轻量备份恢复完成：{filename}')
            committed = True
        except Exception as error:
            failure = error
            rollback_errors: list[str] = []
            for relative_text in reversed(installed_new):
                current = self.server_root / Path(relative_text)
                try:
                    current.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(f'移除已恢复文件失败 {relative_text}：{rollback_error}')
            for relative_text in reversed(moved_old):
                saved = rollback / Path(relative_text)
                if not saved.is_file():
                    continue
                current = self.server_root / Path(relative_text)
                current.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(saved), str(current))
                except OSError as rollback_error:
                    rollback_errors.append(f'还原文件失败 {relative_text}：{rollback_error}')
            remaining = [item for item in rollback.rglob('*') if item.is_file()]
            if remaining:
                rollback_errors.append(f'回滚目录仍有 {len(remaining)} 个文件')
            rollback_ok = not rollback_errors
            if rollback_ok:
                self.log(f'轻量恢复失败，已回滚：{filename}', 'ERROR')
            else:
                failure = PanelError(f'轻量恢复失败且自动回滚不完整；服务器已保持关闭。请保留 {rollback}。详情：{'；'.join(rollback_errors)}')
                self.log(str(failure), 'CRITICAL')
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if committed:
                shutil.rmtree(rollback, ignore_errors=True)
            elif rollback_ok:
                shutil.rmtree(rollback, ignore_errors=True)
        if failure is not None:
            if rollback_ok:
                if maintenance_owned:
                    self.maintenance_flag_path.unlink(missing_ok=True)
            raise failure
        if maintenance_owned:
            self.maintenance_flag_path.unlink(missing_ok=True)
        if restart_after:
            self.stop_flag_path.unlink(missing_ok=True)
            self.start_server()
            self.log('轻量恢复完成后已提交开服请求。')

    def restore_backup(self, filename: str, confirmation: str, restart_after: bool=True) -> None:
        self._require_stopped_for_backup()
        target = self._validated_backup_path(filename)
        if confirmation != filename:
            raise PanelError('恢复确认内容与备份文件名不一致。')
        if self._backup_archive_mode(target) == 'light':
            if self.platform_profile()['family'] != 'java':
                raise PanelError('轻量备份仅支持 Java 游戏服务器。')
            self._restore_light_backup(target, filename, restart_after)
            return
        original_pid = self.validated_server_pid()
        server_was_running = False
        backup_root = (self.server_root / 'backups').resolve()
        staging = Path(tempfile.mkdtemp(prefix='.restore-staging-', dir=backup_root)).resolve()
        rollback = (backup_root / f'.restore-rollback-{uuid.uuid4().hex[:10]}').resolve()
        rollback.mkdir(parents=True, exist_ok=False)
        restore_items = self._platform_backup_items() or ('config', 'defaultconfigs', 'server.properties', 'ops.json', 'whitelist.json', 'banned-players.json', 'banned-ips.json', 'usercache.json', 'user_jvm_args.txt')
        moved_old: list[str] = []
        installed_new: list[str] = []
        maintenance_owned = False
        shutdown_started = False
        committed = False
        rollback_ok = True
        failure: Exception | None = None
        try:
            self._safe_extract_backup(target, staging)
            spec = self.platform_profile()
            if spec['family'] != 'java' and (not (staging / spec['config_file']).is_file()):
                raise PanelError('该备份不含当前平台的配置文件，不能用于恢复。')
            if spec['family'] == 'java':
                world_layout = self._java_restore_layout(staging)
                restore_items = (*world_layout['worlds'], *restore_items)
            current_pid = self.validated_server_pid()
            if current_pid != original_pid:
                raise PanelError('校验备份期间服务器运行状态发生变化，请稍后重新恢复。')
            self.ensure_not_starting()
            if self.maintenance_flag_path.exists():
                raise PanelError('检测到未结束的维护标记，请先确认上一次备份/恢复状态。')
            self.maintenance_flag_path.write_text('restore', encoding='ascii')
            maintenance_owned = True
            post_lock_pid = self.validated_server_pid()
            self.ensure_not_starting()
            if post_lock_pid != original_pid:
                raise PanelError('建立维护锁时服务器状态发生变化，恢复已取消。')
            self.stop_flag_path.write_text('panel-restore', encoding='ascii')
            time.sleep(0.5)
            if self.validated_server_pid():
                raise PanelError('检测到服务器重新启动，恢复已取消。')
            safety_backup = self._create_full_backup()
            self.log(f'恢复前安全备份已创建：{safety_backup.name}')
            for name in restore_items:
                current = self.server_root / name
                incoming = staging / name
                if not incoming.exists():
                    continue
                if current.exists():
                    (rollback / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(current), str(rollback / name))
                    moved_old.append(name)
                current.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(incoming), str(current))
                installed_new.append(name)
            self.log(f'备份恢复完成：{filename}')
            committed = True
        except Exception as error:
            failure = error
            rollback_errors: list[str] = []
            for name in reversed(installed_new):
                current = self.server_root / name
                try:
                    if current.is_symlink() or current.is_file():
                        current.unlink()
                    elif current.is_dir():
                        shutil.rmtree(current)
                except OSError as rollback_error:
                    rollback_errors.append(f'移除已恢复的 {name} 失败：{rollback_error}')
            for name in reversed(moved_old):
                saved = rollback / name
                if saved.exists():
                    current = self.server_root / name
                    if current.exists():
                        rollback_errors.append(f'{name} 的目标位置仍被占用')
                        continue
                    try:
                        current.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(saved), str(current))
                    except OSError as rollback_error:
                        rollback_errors.append(f'还原 {name} 失败：{rollback_error}')
            remaining = []
            try:
                for directory in sorted((item for item in rollback.rglob('*') if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
                    if not any(directory.iterdir()):
                        directory.rmdir()
                remaining = [item.name for item in rollback.iterdir()]
            except OSError as rollback_error:
                rollback_errors.append(f'检查回滚目录失败：{rollback_error}')
            if remaining:
                rollback_errors.append('回滚目录仍有内容：' + '、'.join(remaining))
            rollback_ok = not rollback_errors
            if rollback_ok:
                self.log(f'恢复失败，已完整回滚到恢复前状态：{filename}', 'ERROR')
            else:
                detail = '；'.join(rollback_errors)
                failure = PanelError(f'恢复失败且自动回滚不完整。服务器已保持关闭；请保留并检查 {rollback}。详情：{detail}')
                self.log(str(failure), 'CRITICAL')
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if committed:
                try:
                    shutil.rmtree(rollback)
                except OSError as cleanup_error:
                    self.log(f'恢复已成功，但旧数据暂存目录清理失败：{rollback}：{cleanup_error}', 'WARN')
            elif rollback_ok:
                try:
                    rollback.rmdir()
                except OSError as cleanup_error:
                    self.log(f'空回滚目录清理失败：{rollback}：{cleanup_error}', 'WARN')
        if failure is not None:
            if rollback_ok:
                if maintenance_owned:
                    self.maintenance_flag_path.unlink(missing_ok=True)
            raise failure
        if maintenance_owned:
            self.maintenance_flag_path.unlink(missing_ok=True)
        if restart_after:
            self.stop_flag_path.unlink(missing_ok=True)
            self.start_server()
            self.log('恢复完成后已提交开服请求。')

    def request_restore_backup(self, filename: str, confirmation: str, restart_after: bool) -> str:
        self._validated_backup_path(filename)
        if confirmation != filename:
            raise PanelError('请输入完整备份文件名进行二次确认。')
        self.start_operation('恢复服务器备份', lambda: self.restore_backup(filename, confirmation, restart_after))
        return '恢复任务已接受；面板会确认停服、创建恢复前备份并执行恢复。'

    def _require_stopped_for_backup(self):
        self.ensure_not_starting()
        if self.validated_server_pid(strict=True):
            raise PanelError('请先正常停止服务器，再进行手动备份或恢复。')
        activity = self._startup_process_snapshot(force=True)
        if (not isinstance(activity, dict)
                or not {'java_pid', 'launcher_pids', 'watchdog_pids'}.issubset(activity)
                or type(activity['java_pid']) is not int
                or not isinstance(activity['launcher_pids'], list)
                or not isinstance(activity['watchdog_pids'], list)
                or any(activity[k] for k in ('java_pid', 'launcher_pids', 'watchdog_pids'))):
            raise PanelError('无法确认服务器及启动器已完全关闭，未执行备份或恢复。')
