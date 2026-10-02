# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
"""Session-bound permanent deletion of an exactly registered, stopped server."""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time
from server_manager import PanelError, atomic_write_json
CONFIRMATION = '同意删除'
TOKEN_SECONDS = 300

def _checked(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
        raise PanelError('目录包含链接、目录联接或重解析点，不能执行永久删除。')
    return info

def _identity(path):
    info = _checked(path)
    if not stat.S_ISDIR(info.st_mode):
        raise PanelError('登记的服务器目录不是普通文件夹。')
    return (info.st_dev, info.st_ino, getattr(info, 'st_birthtime_ns', 0))

def _ancestors(path):
    path = Path(path)
    if not path.is_absolute() or path == Path(path.anchor):
        raise PanelError('不能删除磁盘根目录或相对路径。')
    for item in reversed((path, *path.parents)):
        _checked(item)
    resolved = path.resolve(strict=True)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(path)):
        raise PanelError('服务器目录规范路径已发生变化，请重新核对绑定。')
    _identity(resolved)
    return resolved

def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents

@contextmanager
def _pin(path):
    """On Windows deny directory rename/reparse replacement while enumerating."""
    before = _identity(path)
    handle = None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes, close.restype = ([wintypes.HANDLE], wintypes.BOOL)
        handle = create(str(path), 129, 3, None, 3, 35651584, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        if before != _identity(path):
            raise PanelError('目录身份已改变，删除已取消。')
        yield
    finally:
        if handle is not None:
            close(handle)

def inspect_tree(path):
    counts = {'file_count': 0, 'directory_count': 0, 'size_bytes': 0}

    def visit(folder):
        with _pin(folder):
            for item in folder.iterdir():
                info = _checked(item)
                if stat.S_ISDIR(info.st_mode):
                    counts['directory_count'] += 1
                    visit(item)
                elif stat.S_ISREG(info.st_mode):
                    counts['file_count'] += 1
                    counts['size_bytes'] += info.st_size
                else:
                    raise PanelError('目录中存在非普通文件，删除已取消。')
    visit(path)
    return counts

def remove_tree(path, identity):
    """No shell, no link traversal, no chmod of possibly hard-linked files."""
    if _identity(path) != identity:
        raise PanelError('目录身份已改变，删除已取消。')
    with _pin(path):
        for item in path.iterdir():
            info = _checked(item)
            if stat.S_ISDIR(info.st_mode):
                remove_tree(item, _identity(item))
            elif stat.S_ISREG(info.st_mode):
                item.unlink()
            else:
                raise PanelError('目录中出现非普通文件，删除已停止。')
    if _identity(path) != identity:
        raise PanelError('目录身份已改变，删除已停止。')
    path.rmdir()

@contextmanager
def _lock(lock, description):
    if lock is None:
        yield
        return
    if not lock.acquire(blocking=False):
        raise PanelError(description + '，请等待完成后再删除。')
    try:
        yield
    finally:
        lock.release()

class NativeServerDeletion:

    def __init__(self, host, bundle_root):
        self.host = host
        self.bundle_root = Path(bundle_root).resolve()

    def _context(self, identifier):
        if not isinstance(identifier, str) or not identifier:
            raise PanelError('请选择当前账号中要删除的服务器。')
        host = self.host
        host.edition.require_server(host.account['id'], identifier)
        rows = [row for row in host.read_registry(host.account)['servers'] if row['id'] == identifier]
        if len(rows) != 1 or host.registry is None:
            raise PanelError('服务器不属于当前可管理工作区，或其绑定无法核实。')
        context = host.registry.get_context(identifier)
        if Path(rows[0]['path']) != Path(context.definition['path']):
            raise PanelError('服务器绑定已改变，请重新加载工作区。')
        return (context, rows[0])

    def _paths(self, context):
        host = self.host
        root = _ancestors(context.definition['path'])
        if root != context.manager.server_root.resolve():
            raise PanelError('服务器管理路径与登记路径不一致。')
        protected = [host.root.resolve(), Path(sys.executable).resolve().parent]
        for key in ('SystemRoot', 'WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'):
            if os.environ.get(key):
                protected.append(Path(os.environ[key]).resolve())
        if any((_overlap(root, item) for item in protected)):
            raise PanelError('不能删除系统、运行环境、面板数据目录或其上下级目录。')
        if _overlap(root, self.bundle_root):
            container = self.bundle_root / 'mcSever'
            if container not in root.parents:
                raise PanelError('不能删除面板程序目录；仅允许 mcSever 中的独立服务器目录。')
        home = Path.home().resolve()
        if root == home or root in home.parents:
            raise PanelError('不能删除用户主目录或其祖先目录。')
        for profile in host.accounts.accounts():
            for row in host.read_registry(profile)['servers']:
                if profile['id'] == host.account['id'] and row['id'] == context.definition['id']:
                    continue
                if _overlap(root, Path(row['path']).resolve()):
                    raise PanelError('这个目录与其他服务器绑定重叠，不能永久删除。')
        owner = host.workspace_record.get('legacy_owner_id')
        if owner and (not (host.root / 'profiles' / owner / 'data/servers.json').is_file()):
            legacy = self._json(host.root / 'data/servers.json')
            for row in legacy.get('servers', []):
                if _overlap(root, Path(row['path']).resolve()):
                    raise PanelError('目录仍由待迁移工作区保留，不能永久删除。')
        data = host.profile_root(host.account) / 'data/servers' / context.definition['id']
        if data.exists():
            _ancestors(data)
            if context.manager.data_root.resolve() != data.resolve():
                raise PanelError('服务器关联配置路径无法核实。')
        return (root, data)

    @staticmethod
    def _json(path):
        if not path.exists():
            return {}
        _checked(path)
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, ValueError):
            raise PanelError('关联配置无法读取，已取消删除并保留原文件。') from None

    def _idle(self, context):
        host, manager = (self.host, context.manager)
        key = (host.account['id'], context.definition['id'])
        with host.pending_lock:
            if any((item[:2] == key for item in host.pending)):
                raise PanelError('服务器后台任务正在执行，不能删除。')
        with host.install_lock:
            if any((item.get('active') for item in host.install_jobs.values())):
                raise PanelError('后台安装尚未完成，不能删除服务器。')
        state = manager.get_status()
        server = state.get('server', {})
        if server.get('status_known') is not True or server.get('status_stale') is not False or server.get('monitor_error'):
            raise PanelError('无法确认服务器已关闭，请刷新状态后再删除。')
        if server.get('running') or server.get('starting') or server.get('pid') or (server.get('state') not in {'offline', 'crashed', 'startup_failed'}) or state.get('operation', {}).get('active') or state.get('shutdown_countdown', {}).get('active'):
            raise PanelError('服务器仍在运行、启动、停服或执行操作，不能删除。')
        if manager._startup_waiting or any((path.exists() for path in (manager.starting_flag_path, manager.maintenance_flag_path, manager.light_backup_marker_path))):
            raise PanelError('服务器启动或维护标记仍存在，不能删除。')
        if manager.watchdog_enabled():
            raise PanelError('请先关闭服务器守护，再永久删除。')
        from native_exit import NativeExit
        if NativeExit._verified_pid(context) or manager._read_watchdog_pid(validate_command=True):
            raise PanelError('检测到服务器或守护进程仍在运行，不能删除。')
        from native_platform_config import read_endpoint
        props = read_endpoint(manager.server_root, manager.platform)
        try:
            port = int(props.get('server-port', '25565'))
            if not 1 <= port <= 65535:
                raise ValueError()
            address = manager._normalize_server_bind(props.get('server-ip', ''))
        except (TypeError, ValueError):
            raise PanelError('服务器监听配置无效，无法安全核实停服状态。') from None
        from native_platforms import profile as platform_profile
        manager._check_server_endpoint_available({'server-ip': address, 'server-port': port, 'network_protocol': manager.platform_profile()['network_protocol']})

    @contextmanager
    def _locked(self, context):
        manager = context.manager
        with ExitStack() as stack:
            for lock, label in ((manager._mutation_lock, '服务器配置或操作仍被占用'), (manager._shutdown_countdown_lock, '停服通知仍在执行'), (manager._operation_lock, '服务器操作仍在执行')):
                stack.enter_context(_lock(lock, label))
            self._idle(context)
            yield

    def preview(self, payload):
        host = self.host
        host.session().pop('delete_preview', None)
        context, row = self._context(payload.get('id'))
        with self._locked(context):
            root, data = self._paths(context)
            counts = inspect_tree(root)
            if data.exists():
                inspect_tree(data)
            token = secrets.token_urlsafe(32)
            host.session()['delete_preview'] = {'token': token, 'account_id': host.account['id'], 'id': row['id'], 'path': str(root), 'identity': _identity(root), 'definition': dict(row), 'expires': time.monotonic() + TOKEN_SECONDS}
        return {'id': row['id'], 'name': row['name'], 'path': str(root), 'token': token, 'expires_in_seconds': TOKEN_SECONDS, 'confirmation_text': CONFIRMATION, 'permanent': True, **counts, 'message': '将永久删除整个服务器文件夹（包括世界、模组、配置和文件夹内的备份），并清除面板关联配置与任务。此操作无法撤销。'}

    def delete(self, payload):
        host = self.host
        receipt = host.session().pop('delete_preview', None)
        if not receipt or not isinstance(payload.get('token'), str) or (not secrets.compare_digest(receipt['token'], payload['token'])) or (receipt['expires'] < time.monotonic()) or (receipt['account_id'] != host.account['id']):
            raise PanelError('删除确认已失效，请重新打开删除窗口。')
        if payload.get('confirmation') != CONFIRMATION:
            raise PanelError('必须准确输入“同意删除”，已取消删除。')
        if payload.get('id') != receipt['id'] or payload.get('path') != receipt['path']:
            raise PanelError('删除对象与已确认目录不一致，已取消删除。')
        context, row = self._context(receipt['id'])
        if row != receipt['definition']:
            raise PanelError('服务器绑定已改变，请重新确认删除。')
        preferences = self._preferences(row['id'])
        with self._locked(context):
            root, data = self._paths(context)
            if _identity(root) != receipt['identity']:
                raise PanelError('服务器文件夹已被替换，请重新核对。')
            inspect_tree(root)
            if data.exists():
                inspect_tree(data)
            context.manager._stop_event.set()
        context.manager.stop_monitor()
        if any(thread is not None and thread.is_alive() for thread in (
                context.manager._monitor_thread, context.manager._player_history_thread,
                context.manager._shutdown_countdown_thread)):
            raise PanelError('服务器后台线程尚未退出，已保留目录和绑定，请稍后重新确认。')
        with self._locked(context):
            root, data = self._paths(context)
            if _identity(root) != receipt['identity']:
                raise PanelError('服务器目录身份已变化，删除已取消。')
            try:
                with ExitStack() as stack:
                    for parent in reversed(root.parents):
                        stack.enter_context(_pin(parent))
                    inspect_tree(root)
                    remove_tree(root, receipt['identity'])
                if data.exists():
                    with ExitStack() as stack:
                        for parent in reversed(data.parents):
                            stack.enter_context(_pin(parent))
                        remove_tree(data, _identity(data))
                for path, value in preferences:
                    atomic_write_json(path, value)
                active = host.registry.finalize_deleted_server(row['id'])
            except Exception as error:
                raise PanelError('删除未完成，服务器绑定已保留；部分文件可能已删除，后台任务已暂停。请检查目录与权限，不要自动重试。原因：' + str(error)) from error
        host.edition.release(host.account['id'], row['id'])
        key = (host.account['id'], row['id'])
        empty = not host.registry.contexts()
        sessions = [host.session(), host.local_session]
        for session in sessions:
            if (session.get('account') or {}).get('id') != host.account['id']:
                continue
            if session.get('selected_server_id') == row['id']:
                session['selected_server_id'] = ''
            session.pop('delete_preview', None)
            if empty:
                session['registry'] = None
        if empty:
            host.registries.pop(host.account['id'], None)
            host.registry = None
        return {'id': row['id'], 'deleted': True, 'active_server_id': active, 'message': '服务器文件夹及关联配置、任务已永久删除。'}

    def _preferences(self, identifier):
        path = self.host.profile_root(self.host.account) / 'portable-servers.json'
        if not path.exists():
            return []
        value = self._json(path)
        value.pop(identifier, None)
        return [(path, value)]
