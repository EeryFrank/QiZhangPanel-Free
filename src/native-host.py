# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
"""Native panel engine: private inherited stdin/stdout IPC, no HTTP server."""
from __future__ import annotations
import argparse
import base64
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socket
import shutil
import sys
import subprocess
import threading
import time
import traceback
import uuid
VERSION = '2.5.7'
ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))
from server_manager import ServerManager, PanelError
from server_registry import ServerRegistry
from native_accounts import NativeAccounts, NativeAccountError
from single_server_policy import SingleServerPolicy

def migration_module():
    location = ROOT / 'state_store.py'
    spec = importlib.util.spec_from_file_location('native_migration', location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class NativeHost:

    def new_session(self):
        return {'id': uuid.uuid4().hex, 'authenticated': False, 'account': None, 'registry': None, 'failures': [], 'selected_server_id': ''}

    def session(self):
        return getattr(self._request_context, 'session', self.local_session)

    @property
    def account(self):
        return self.session().get('account')

    @account.setter
    def account(self, value):
        self.session()['account'] = value

    @property
    def authenticated(self):
        return self.session().get('authenticated', False)

    @authenticated.setter
    def authenticated(self, value):
        self.session()['authenticated'] = value

    @property
    def registry(self):
        session = self.session()
        profile = session.get('account')
        return self.registries.get(profile['id'], session.get('registry')) if profile else session.get('registry')

    @registry.setter
    def registry(self, value):
        self.session()['registry'] = value

    @property
    def failures(self):
        return self.session()['failures']

    @failures.setter
    def failures(self, value):
        self.session()['failures'] = value

    def __init__(self, state_root: Path, autostart=False):
        self.local_session = self.new_session()
        self._request_context = threading.local()
        self.request_lock = threading.RLock()
        self.root = state_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.edition = SingleServerPolicy(self.root)
        self.migration = migration_module()
        self.migration.protect_state(self.root)
        import msvcrt
        self.lock = (self.root / 'native-host.lock').open('a+b')
        self.lock.seek(0)
        if not self.lock.read(1):
            self.lock.write(b'0')
            self.lock.flush()
        self.lock.seek(0)
        try:
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock.close()
            raise PanelError('独立面板后台已在运行，请从托盘打开现有窗口。')
        self.registry = None
        self.registries = {}
        self.workspace_errors = {}
        self.install_jobs = {}
        self.archive_previews = {}
        self.install_lock = threading.RLock()
        self._diagnostic_preview = None
        self.account = None
        self.authenticated = False
        self.failures = []
        self.pending = set()
        self.pending_lock = threading.Lock()
        self.exiting = False
        from native_exit import NativeExit
        self.exit_controller = NativeExit(self)
        self.started = time.monotonic()
        self.autostart = False
        self.executable = ROOT / '七章控制面板.exe'
        self.startup_enabled = False
        self.import_rollback = None
        self.import_pending = False
        try:
            self.accounts = NativeAccounts(self.root / 'accounts.json', self.migration.read_json(self.root / 'data/panel-config.json', {}))
            self.workspace_record = self.migration.read_json(self.root / 'native-workspaces.json', {})
            profiles = self.accounts.accounts()
            if (self.root / 'data/servers.json').is_file() and (not self.workspace_record.get('legacy_owner_id')) and profiles:
                self.assign_legacy(profiles[0])
            for profile in profiles:
                self.prepare_workspace(profile)
                registry = self.safe_load_workspace(profile)
                if self.software_settings(profile).get('auto_start_panel'):
                    self.startup_enabled = True
            ServerManager.set_panel_autostart = lambda manager, enabled: self.set_autostart(manager, enabled)
            self.migration.write_json(self.root / 'native-state.json', {'pid': os.getpid(), 'version': VERSION, 'transport': 'stdio'})
            self.autostart = False
        except Exception:
            self.close()
            raise

    def profile_root(self, profile):
        return self.root / 'profiles' / str(uuid.UUID(profile['id']))

    def read_registry(self, profile):
        path = self.profile_root(profile) / 'data/servers.json'
        if not path.exists():
            return {'servers': [], 'active_server_id': ''}
        try:
            record = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(record, dict) or not isinstance(record.get('servers'), list):
                raise ValueError()
            if any((not isinstance(item, dict) or not item.get('id') or (not item.get('path')) for item in record['servers'])):
                raise ValueError()
            return record
        except (ValueError, OSError, UnicodeError):
            raise PanelError('服务器列表文件损坏或无法读取。已保留原文件，请从备份恢复 servers.json。') from None

    def check_free_capacity(self, *, include_pending=True):
        if self.edition.slot_error:
            raise PanelError(self.edition.slot_error)
        total = sum((len(self.read_registry(profile).get('servers', [])) for profile in self.accounts.accounts()))
        if not self.workspace_record.get('legacy_owner_id') and (self.root / 'data/servers.json').exists():
            total += len(self.migration.read_json(self.root / 'data/servers.json', {}).get('servers', []))
        if total or self.edition.slot or (include_pending and any((job.get('active') for job in self.install_jobs.values()))):
            raise PanelError('免费版在整个安装中最多绑定一台服务器（所有账号共用）。现有服务器和配置已保留，可选择管理槽位或移除多余面板绑定。')

    def free_servers_list(self, profile):
        record = self.read_registry(profile)
        live = self.registries.get(profile['id'])
        statuses = {row['id']: row for row in live.list_servers()['servers']} if live else {}
        servers = []
        for item in record.get('servers', []):
            row = {**item, **statuses.get(item['id'], {})}
            from native_platforms import profile as platform_profile
            row['platform_profile'] = platform_profile(item.get('platform', 'vanilla'), item.get('path'))
            locked = not self.edition.owns(profile['id'], item['id'])
            row.update(edition_locked=locked, edition_lock_reason='免费版只提供一个管理槽位；此服务器文件和配置已保留。' if locked else '')
            if item['id'] not in statuses:
                row.update(state='unknown', status_known=False, status_stale=True, operation={}, shutdown_countdown={})
            servers.append(row)
        selected = self.edition.slot['server_id'] if self.edition.slot and self.edition.slot['account_id'] == profile['id'] else ''
        edition = self.edition.describe(profile['id'])
        try:
            self.check_free_capacity()
            edition['can_add_server'] = True
        except PanelError:
            edition['can_add_server'] = False
        return {'servers': servers, 'active_server_id': selected, 'workspace_error': self.workspace_errors.get(profile['id'], ''), 'edition': edition}

    def select_free_server(self, payload):
        if payload.get('account_id', self.account['id']) != self.account['id']:
            raise PanelError('只能选择当前账号的服务器。')
        identifier = str(payload.get('id', ''))
        definition = next((item for item in self.read_registry(self.account).get('servers', []) if item['id'] == identifier), None)
        if not definition:
            raise PanelError('当前账号没有这台服务器。')
        ServerRegistry._validated_definition(definition)
        self.edition.bind(self.account['id'], identifier)
        self.registry = self.safe_load_workspace(self.account)
        return {'edition': self.edition.describe(self.account['id']), 'server': definition, 'message': '已选择免费版管理槽位；不会自动启动游戏服务器。'}

    def remove_free_binding(self, identifier):
        profile = self.account
        record = self.read_registry(profile)
        definition = next((item for item in record.get('servers', []) if item['id'] == identifier), None)
        if not definition:
            raise PanelError('指定服务器不存在。')
        with self.pending_lock:
            if any((key[:2] == (profile['id'], identifier) for key in self.pending)):
                raise PanelError('这台服务器有任务正在执行。')
        registry = self.registries.get(profile['id'])
        if registry and self.edition.owns(profile['id'], identifier):
            context = registry.get_context(identifier)
            state = context.manager.get_status()
            if state.get('operation', {}).get('active') or state.get('shutdown_countdown', {}).get('active') or context.manager.validated_server_pid() or context.manager.starting_flag_path.exists():
                raise PanelError('请先手动停止这台服务器并等待操作结束，再移除管理槽位绑定。')
            context.manager.stop_monitor()
            self.registries.pop(profile['id'], None)
            self.registry = None
        remaining = [item for item in record['servers'] if item['id'] != identifier]
        active = record.get('active_server_id', '')
        if active == identifier:
            active = remaining[0]['id'] if remaining else ''
        self.migration.write_json(self.profile_root(profile) / 'data/servers.json', {**record, 'servers': remaining, 'active_server_id': active})
        self.edition.release(profile['id'], identifier)
        return {'server': definition, 'edition': self.edition.describe(profile['id']), 'message': '已移除面板绑定，服务器文件和原配置均保留。'}

    def software_settings(self, profile):
        root = self.profile_root(profile)
        legacy = self.migration.read_json(root / 'data/panel-config.json', {})
        saved = self.migration.read_json(root / 'software.json', {})
        hidden = saved.get('hide_server_launcher_windows', True)
        return {'auto_start_panel': bool(saved.get('auto_start_panel', legacy.get('auto_start_panel', False))), 'startup_permission': saved.get('startup_permission', 'normal'), 'hide_server_launcher_windows': hidden if isinstance(hidden, bool) else True}

    def claim_installer_startup(self, profile):
        """Transfer a fresh installer preference to the first local account once.

        The installer already configured Windows. Login only records ownership;
        it must never register tasks, elevate, or recreate startup shortcuts.
        """
        pending_file = self.root / 'installer-startup-pending.json'
        try:
            pending = self.migration.read_json(pending_file, {})
            if not isinstance(pending, dict) or pending.get('owner') != 'QiZhangInstaller' or type(pending.get('schema')) is not int or (pending['schema'] != 1) or (not isinstance(pending.get('enabled'), bool)) or (pending.get('mode') != 'normal') or ('claimed_account_id' in pending):
                return
            accounts = self.accounts.accounts()
            if not accounts or accounts[0]['id'] != profile['id']:
                return
            destination = self.profile_root(profile) / 'software.json'
            if not destination.exists():
                self.migration.write_json(destination, {'auto_start_panel': pending['enabled'], 'startup_permission': 'normal', 'hide_server_launcher_windows': True})
            self.migration.write_json(pending_file, {**pending, 'claimed_account_id': profile['id']})
            self.startup_enabled = any((self.software_settings(account)['auto_start_panel'] for account in accounts))
        except (OSError, ValueError, TypeError):
            return

    def remember_portable_server(self, profile, definition):
        file = self.profile_root(profile) / 'portable-servers.json'
        mapping = self.migration.read_json(file, {})
        try:
            relative = Path(definition['path']).resolve().relative_to(ROOT.resolve())
            if not relative.parts or relative.parts[0].casefold() != 'mcsever':
                raise ValueError()
            mapping[definition['id']] = {'relative_path': relative.as_posix(), 'last_absolute_path': definition['path']}
        except ValueError:
            mapping.pop(definition['id'], None)
        self.migration.write_json(file, mapping)

    def relocate_portable_servers(self, profile, record):
        file = self.profile_root(profile) / 'portable-servers.json'
        mapping = self.migration.read_json(file, {})
        changed = False
        for definition in record.get('servers', []):
            item = mapping.get(definition['id'], {})
            relative = Path(item.get('relative_path', ''))
            destination = (ROOT / relative).resolve()
            if not relative.parts or relative.is_absolute() or relative.parts[0].casefold() != 'mcsever' or (not destination.is_relative_to((ROOT / 'mcSever').resolve())):
                continue
            if str(Path(definition['path']).resolve()) != item.get('last_absolute_path') or destination == Path(definition['path']).resolve() or (not (destination / definition.get('launch_script', '')).is_file()):
                continue
            updated = ServerRegistry._validated_definition({**definition, 'path': str(destination)})
            self.check_server_owner(destination, profile['id'])
            definition.update(updated)
            item['last_absolute_path'] = str(destination)
            changed = True
        if changed:
            self.migration.write_json(self.profile_root(profile) / 'data/servers.json', record)
            self.migration.write_json(file, mapping)
        return record

    def update_software_settings(self, profile, payload):
        allowed = {'auto_start_panel', 'startup_permission', 'hide_server_launcher_windows'}
        if set(payload) - allowed:
            raise PanelError('软件设置包含不支持的字段。')
        current = self.software_settings(profile)
        enabled = payload.get('auto_start_panel', current['auto_start_panel'])
        permission = payload.get('startup_permission', current['startup_permission'])
        hidden = payload.get('hide_server_launcher_windows', current['hide_server_launcher_windows'])
        if not isinstance(enabled, bool) or not isinstance(hidden, bool) or permission not in {'normal', 'administrator'}:
            raise PanelError('开机启动、权限或窗口隐藏设置格式无效。')
        other = [self.software_settings(p) for p in self.accounts.accounts() if p['id'] != profile['id']]
        desired = enabled or any((p['auto_start_panel'] for p in other))
        elevated = enabled and permission == 'administrator' or any((p['auto_start_panel'] and p['startup_permission'] == 'administrator' for p in other))
        desired_permission = 'administrator' if elevated else 'normal'
        if not self.executable.is_file():
            raise PanelError('请从完整程序包启动后设置开机启动。')
        from native_startup import configure
        configure(desired, desired_permission, self.executable, self.root)
        self.startup_enabled = desired
        saved = {'auto_start_panel': enabled, 'startup_permission': permission, 'hide_server_launcher_windows': hidden}
        self.migration.write_json(self.profile_root(profile) / 'software.json', saved)
        registry = self.registries.get(profile['id'])
        if registry:
            for context in registry.contexts():
                context.manager.hide_launcher_windows = hidden
        return {**saved, 'effective_startup_permission': desired_permission, 'message': '软件设置已保存。'}

    def assign_legacy(self, profile):
        self.workspace_record['legacy_owner_id'] = profile['id']
        self.migration.write_json(self.root / 'native-workspaces.json', self.workspace_record)

    def prepare_workspace(self, profile):
        root = self.profile_root(profile)
        root.mkdir(parents=True, exist_ok=True)
        if self.workspace_record.get('legacy_owner_id') == profile['id'] and (not (root / 'data').exists()):
            staging = root / ('import-' + uuid.uuid4().hex)
            shutil.copytree(self.root / 'data', staging)
            staging.rename(root / 'data')
        return root

    def load_workspace(self, profile):
        if profile['id'] in self.registries:
            return self.registries[profile['id']]
        root = self.prepare_workspace(profile)
        record = self.read_registry(profile)
        if self.edition.slot_error or not self.edition.slot or self.edition.slot['account_id'] != profile['id']:
            return None
        selected = self.edition.slot['server_id']
        definitions = [item for item in record.get('servers', []) if item['id'] == selected]
        if not definitions:
            return None
        if not definitions:
            return None
        for definition in definitions:
            ServerRegistry._validated_definition(definition)
            self.check_server_owner(definition['path'], profile['id'])
        os.environ['PYTHON'] = sys.executable
        shutil.copytree(ROOT / 'backend/tools', root / 'tools', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        registry = ServerRegistry(root, Path(definitions[0]['path']), runtime_policy=self.edition, managed_server_id=definitions[0]['id'])
        self.registries[profile['id']] = registry
        for context in registry.contexts():
            manager = context.manager
            self.configure_manager(manager, profile['id'])
            manager.start_monitor()
        return registry

    def configure_manager(self, manager, account_id):
        manager.native_account_id = account_id
        manager.hide_launcher_windows = self.software_settings({'id': account_id})['hide_server_launcher_windows']

    def safe_load_workspace(self, profile):
        try:
            registry = self.load_workspace(profile)
            self.workspace_errors.pop(profile['id'], None)
            return registry
        except PanelError as error:
            self.workspace_errors[profile['id']] = str(error)
            return None

    def check_server_owner(self, path, owner_id):
        candidate = Path(path).resolve()

        def overlaps(value):
            other = Path(value).resolve()
            return candidate == other or candidate in other.parents or other in candidate.parents
        for file in (self.root / 'profiles').glob('*/data/servers.json'):
            if file.parent.parent.name == owner_id:
                continue
            for definition in self.migration.read_json(file, {}).get('servers', []):
                if overlaps(definition['path']):
                    raise PanelError('这个服务器目录或其上下级目录已经属于另一个账号的工作区。')
        legacy_owner = self.workspace_record.get('legacy_owner_id')
        if legacy_owner and legacy_owner != owner_id:
            if not (self.root / 'profiles' / legacy_owner / 'data/servers.json').is_file():
                for definition in self.migration.read_json(self.root / 'data/servers.json', {}).get('servers', []):
                    if overlaps(definition['path']):
                        raise PanelError('这个服务器目录或其上下级目录已保留给原账号工作区。')

    def activate(self, profile):
        self.session().pop('delete_preview', None)
        self.authenticated = False
        self.account = None
        self.registry = None
        if not self.workspace_record.get('legacy_owner_id') and (self.root / 'data/servers.json').is_file():
            self.assign_legacy(profile)
        registry = self.safe_load_workspace(profile)
        self.account, self.registry = (profile, registry)
        self.authenticated = True
        self.claim_installer_startup(profile)
        preferences = self.software_settings(profile)
        outcomes = []
        return {'authenticated': True, 'account': profile, 'edition': self.edition.describe(profile['id'])}

    def set_autostart(self, manager, enabled):
        return

    def check_registered_endpoint(self, manager, properties):
        endpoint = manager.requested_server_endpoint(properties)
        if endpoint is None:
            return
        from native_platforms import profile as platform_profile
        endpoint['network_protocol'] = manager.platform_profile()['network_protocol']
        for profile in self.accounts.accounts():
            for item in self.read_registry(profile).get('servers', []):
                other = Path(item['path'])
                if other.resolve() == manager.server_root.resolve():
                    continue
                try:
                    from native_platform_config import read_endpoint
                    other_endpoint = read_endpoint(other, item.get('platform', 'vanilla'))
                    same_protocol = other_endpoint['network_protocol'] == endpoint.get('network_protocol', 'TCP')
                    if same_protocol and int(other_endpoint['server-port']) == int(endpoint['server-port']):
                        raise PanelError('这个端口已分配给面板中的其他服务器，请使用不同端口。')
                    if endpoint.get('network_protocol', 'TCP') == 'TCP':
                        text = (other / 'server.properties').read_text(encoding='utf-8-sig') if (other / 'server.properties').is_file() else ''
                        if re.search('(?m)^enable-rcon\\s*=\\s*true\\s*$', text):
                            rcon = re.search('(?m)^rcon\\.port\\s*=\\s*(\\d+)', text)
                            if rcon and int(rcon[1]) == int(endpoint['server-port']):
                                raise PanelError('这个端口已分配给其他服务的 RCON，请使用不同端口。')
                except (OSError, ValueError):
                    continue

    def start_archive_preview(self, payload):
        from native_server_archive import ArchivePreviewSession
        from native_server_install import validate_server_dir
        self.check_free_capacity()
        archive = Path(str(payload.get('archive', '')))
        if archive.suffix.lower() != '.zip' or not archive.is_file():
            raise PanelError('请选择存在的服务器 ZIP 压缩包。')
        destination = validate_server_dir(payload.get('path', ''))
        self.check_server_owner(destination, self.account['id'])
        if type(payload.get('adapt_startup', True)) is not bool:
            raise PanelError('启动适配选项格式无效。')
        owner = self.account['id']
        job_id = uuid.uuid4().hex
        with self.install_lock:
            if any((item.get('active') for item in self.install_jobs.values())):
                raise PanelError('已有扫描或安装任务正在进行，请等待完成。')
            session = self.archive_previews.get(owner)
            if session is None:
                session = ArchivePreviewSession(self.root / 'install-cache' / ('preview-' + owner))
                self.archive_previews[owner] = session
            self.install_jobs[owner] = {'job_id': job_id, 'active': True, 'phase': 'previewing', 'progress': 0, 'message': '正在解压并检查启动配置…', 'error': ''}
        key = (owner, 'archive-preview', job_id)
        with self.pending_lock:
            self.pending.add(key)

        def progress(percent, message):
            with self.install_lock:
                self.install_jobs[owner].update(progress=int(percent), message=str(message))

        def scan():
            try:
                preview = session.prepare(str(archive), java_path=payload.get('java_path', ''), selected_core=payload.get('selected_core'), adapt_startup=payload.get('adapt_startup', True), on_progress=progress, server_dir=str(destination))
                with self.install_lock:
                    self.install_jobs[owner].update(active=False, phase='previewed', progress=100, preview=preview, message='识别完成，请检查预览后确认导入。', error='')
            except Exception as error:
                with self.install_lock:
                    self.install_jobs[owner].update(active=False, phase='failed', message='识别未完成。', error=str(error))
            finally:
                with self.pending_lock:
                    self.pending.discard(key)
        threading.Thread(target=scan, name='QiZhang-Archive-Preview', daemon=False).start()
        return {'job_id': job_id, 'message': '已开始识别服务器。'}

    def start_server_install(self, payload, from_archive=False):
        from native_server_archive import ArchiveSelectionRequired
        self.check_free_capacity()
        if self.workspace_errors.get(self.account['id']):
            raise PanelError('请先修复当前工作区的服务器目录，再安装。')
        from native_server_install import validate_server_dir
        name = str(payload.get('name', '')).strip()
        if not 1 <= len(name) <= 40:
            raise PanelError('服务器名称需要 1～40 个字符。')
        destination = validate_server_dir(payload.get('path', ''))
        java_choice = payload.get('java_path', '')
        java = java_choice
        self.check_server_owner(destination, self.account['id'])
        from native_platforms import PLATFORMS, profile as platform_profile
        if not from_archive and payload.get('platform') not in PLATFORMS:
            raise PanelError('请选择受支持的服务端类型。')
        if not from_archive and (not isinstance(payload.get('eula_accepted', False), bool)):
            raise PanelError('协议选项格式无效。')
        if from_archive and (Path(str(payload.get('archive', ''))).suffix.lower() != '.zip' or not Path(str(payload.get('archive', ''))).is_file()):
            raise PanelError('请选择存在的服务器 ZIP 压缩包。')
        selected_core = payload.get('selected_core')
        adapt_startup = payload.get('adapt_startup', True)
        if from_archive and type(adapt_startup) is not bool:
            raise PanelError('启动适配选项格式无效，请重新勾选后导入。')
        if selected_core is not None and (not isinstance(selected_core, str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}', selected_core)):
            raise PanelError('启动目标标识无效，请重新扫描压缩包并选择。')
        profile = dict(self.account)
        identifier = profile['id']
        job_id = uuid.uuid4().hex
        with self.install_lock:
            if any((item.get('active') for item in self.install_jobs.values())):
                raise PanelError('已有服务端正在安装，请等待完成后再安装下一台。')
            self.install_jobs[identifier] = {'job_id': job_id, 'active': True, 'phase': 'installing', 'progress': 0, 'message': '准备安装…', 'error': ''}
        key = (identifier, 'server-install', job_id)
        with self.pending_lock:
            self.pending.add(key)

        def progress(percent, message):
            with self.install_lock:
                self.install_jobs[identifier].update(progress=int(percent), message=str(message))

        def install():
            try:
                cache = self.root / 'install-cache'
                if from_archive:
                    from native_server_archive import install_archive
                    preview_token = payload.get('preview_token')
                    if preview_token:
                        preview = self.archive_previews.get(identifier)
                        if preview is None:
                            raise PanelError('导入预览已失效，请重新识别压缩包。')
                        definition = preview.install(preview_token, payload['archive'], destination, java, progress, selected_core=selected_core, adapt_startup=adapt_startup, cache_root=cache)
                    else:
                        definition = install_archive(payload['archive'], destination, java, progress, cache_root=cache, selected_core=selected_core, adapt_startup=adapt_startup)
                else:
                    from native_server_install import install_server
                    definition = install_server(payload['platform'], destination, java, progress, eula_accepted=payload.get('eula_accepted', False), minecraft_version=payload.get('minecraft_version', '1.21.1'), cache_root=cache, loader_version=payload.get('loader_version') or None)
                definition['name'] = name
                java_selection = definition.get('java_selection', {})
                startup_adaptation = definition.get('startup_adaptation', {})
                java_message = str(java_selection.get('message', ''))
                java_major = definition.get('java_major', 21 if not from_archive else None)
                if not java_message and java_major:
                    java_message = f'已选择 Java {java_major}。'
                definition.setdefault('id', 'server-' + uuid.uuid4().hex[:8])
                self.check_server_owner(destination, identifier)
                with self.request_lock:
                    port = self.reserve_game_port(destination, definition.get('platform', 'vanilla'))
                    root = self.prepare_workspace(profile)
                    self.check_free_capacity(include_pending=False)
                    registry = self.registries.get(identifier)
                    if registry:
                        definition = registry.add_server(definition)
                        self.configure_manager(registry.get_context(definition['id']).manager, identifier)
                    else:
                        (root / 'data').mkdir(exist_ok=True)
                        self.migration.write_json(root / 'data/servers.json', {'version': 1, 'servers': [definition], 'active_server_id': definition['id']})
                        self.edition.bind(identifier, definition['id'])
                        registry = self.load_workspace(profile)
                    if self.account and self.account['id'] == identifier:
                        self.registry = registry
                    self.remember_portable_server(profile, definition)
                with self.install_lock:
                    self.install_jobs[identifier].update(active=False, phase='complete', progress=100, message=f'安装完成，游戏端口 {port}，尚未开服。' + java_message + str(startup_adaptation.get('message', '')), startup_adaptation=startup_adaptation, java_major=java_major, java_selection=java_selection, server_id=definition['id'])
            except ArchiveSelectionRequired as selection:
                with self.install_lock:
                    self.install_jobs[identifier].update(active=False, phase='awaiting_selection', progress=83, error='', message=str(selection), choices=selection.choices)
            except Exception as error:
                with self.install_lock:
                    self.install_jobs[identifier].update(active=False, phase='failed', error=str(error), message='安装未完成，请查看错误；已存在的服务器不会被覆盖。')
            finally:
                with self.pending_lock:
                    self.pending.discard(key)
        threading.Thread(target=install, name='QiZhang-Server-Install', daemon=False).start()
        return {'job_id': job_id, 'message': '安装任务已开始。'}

    def reserve_game_port(self, destination, platform='vanilla'):
        from native_platforms import profile as platform_profile
        from native_platform_config import read_endpoint, write_endpoint
        spec = platform_profile(platform, destination)
        if spec['family'] != 'java':
            if spec['family'] == 'custom':
                return 0
            reserved = set()
            for account in self.accounts.accounts():
                for item in self.read_registry(account).get('servers', []):
                    try:
                        other = read_endpoint(item['path'], item.get('platform', 'vanilla'))
                        if other['network_protocol'] == spec['network_protocol']:
                            reserved.add(int(other['server-port']))
                    except (OSError, ValueError):
                        continue
            endpoint = read_endpoint(destination, platform)
            desired = int(endpoint['server-port'])
            for port in [desired] + list(range(30000, 30100)):
                if port in reserved:
                    continue
                try:
                    from server_manager import ServerManager
                    ServerManager._check_server_endpoint_available({'server-ip': endpoint['server-ip'], 'server-port': port, 'network_protocol': spec['network_protocol']})
                    write_endpoint(destination, platform, endpoint['server-ip'], port)
                    return port
                except (OSError, PanelError):
                    continue
            raise PanelError('没有可用的 ' + spec['network_protocol'] + ' 端口，请调整平台配置后绑定。')
        reserved = set()
        for profile in self.accounts.accounts():
            try:
                record = self.read_registry(profile)
            except PanelError:
                continue
            for item in record.get('servers', []):
                try:
                    other_endpoint = read_endpoint(item['path'], item.get('platform', 'vanilla'))
                    if other_endpoint['network_protocol'] == 'TCP':
                        reserved.add(int(other_endpoint['server-port']))
                    from native_platform_config import _properties
                    props_file = Path(item['path']) / 'server.properties'
                    values = _properties(props_file.read_text(encoding='utf-8-sig')) if props_file.is_file() else {}
                    if values.get('enable-rcon') == 'true':
                        reserved.add(int(values.get('rcon.port', '25575')))
                except (OSError, ValueError):
                    pass
        file = Path(destination) / 'server.properties'
        from native_platform_config import _properties, _replace_properties
        original = file.read_bytes()
        bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
        contents = original.decode('utf-8-sig')
        values = _properties(contents)
        desired = int(values.get('server-port', '25565'))
        candidates = [desired] + list(range(25565, 25666))
        for port in candidates:
            if not 1 <= port <= 65535 or port in reserved:
                continue
            try:
                with socket.socket() as probe:
                    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    probe.bind(('0.0.0.0', port))
            except OSError:
                continue
            updated = _replace_properties(contents, {'server-port': str(port)})
            if values.get('enable-rcon') == 'true':
                desired_rcon = int(values.get('rcon.port', '25575'))
                rcon_candidates = [desired_rcon] + list(range(25575, 25676))
                rcon_port = None
                for candidate in rcon_candidates:
                    if not 1 <= candidate <= 65535 or candidate in reserved or candidate == port:
                        continue
                    try:
                        with socket.socket() as probe:
                            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                            probe.bind(('0.0.0.0', candidate))
                        rcon_port = candidate
                        break
                    except OSError:
                        continue
                if rcon_port is None:
                    raise PanelError('没有可用 RCON 端口，请调整服务端配置后手动添加。')
                updated = _replace_properties(updated, {'rcon.port': str(rcon_port)})
            if file.read_bytes() != original:
                raise PanelError('监听配置已被其他程序修改，请重试；未覆盖原文件。')
            file.write_bytes(bom + updated.encode('utf-8'))
            return port
        raise PanelError('没有可用游戏端口，请保留已安装的文件，调整 server.properties 后手动添加服务器。')

    def busy(self):
        with self.pending_lock:
            if self.pending:
                return True
        for registry in self.registries.values():
            for context in registry.contexts():
                status = context.manager.get_status()
                if status.get('operation', {}).get('active') or status.get('shutdown_countdown', {}).get('active'):
                    return True
        return False

    def async_job(self, key, callback, manager):
        with self.pending_lock:
            if key in self.pending:
                raise PanelError('任务已经在执行，请稍后查看结果。')
            self.pending.add(key)

        def run():
            try:
                callback()
            except Exception as error:
                manager.log(f'后台任务失败：{error}', 'ERROR')
            finally:
                with self.pending_lock:
                    self.pending.discard(key)
        threading.Thread(target=run, name='QiZhang-Native-Job', daemon=False).start()

    def request(self, action, payload, server_id='', session=None):
        with self.request_lock:
            return self._request(action, payload, server_id)

    def _request(self, action, payload, server_id=''):
        if self.exit_controller.blocks_requests and action not in {'panel.exit', 'panel.exit.status', 'panel.exit.prepare', 'hello', 'status', 'logs', 'logs.poll', 'monitoring.metrics', 'servers.list', 'account.get', 'settings.get', 'settings.capabilities', 'launch.settings', 'backups.list', 'software.get', 'software.settings.get'}:
            raise PanelError('正在安全关闭服务器并退出面板，请等待完成；暂不接受新的操作。')
        if action == 'panel.exit.status':
            return self.exit_controller.status()
        if action == 'panel.exit.prepare':
            return self.exit_controller.prepare(payload.get('confirmed'))
        if action == 'panel.exit':
            return self.exit_controller.finish()
        if not isinstance(payload, dict):
            raise PanelError('请求参数格式无效。')
        if action == 'hello':
            remote = False
            return {'version': VERSION, 'transport': 'stdio', 'setup_required': not self.accounts.status()['has_accounts'] and (not remote), 'registration_allowed': not remote, 'authenticated': self.authenticated, 'account': self.account if self.authenticated else None, 'pid': os.getpid(), 'edition': self.edition.describe(self.account['id'] if self.authenticated else None)}
        if action in {'register', 'setup', 'login'}:
            self.failures = [stamp for stamp in self.failures if time.monotonic() - stamp < 60]
            if len(self.failures) >= 8:
                raise PanelError('登录失败次数过多，请 60 秒后重试。')
            try:
                if action in {'register', 'setup'}:
                    profile = self.accounts.register(payload.get('username'), payload.get('password'))
                else:
                    profile = self.accounts.authenticate(payload.get('username'), payload.get('password'))
            except NativeAccountError as error:
                self.failures.append(time.monotonic())
                self.authenticated, self.account, self.registry = (False, None, None)
                raise PanelError(str(error)) from None
            self.failures.clear()
            return self.activate(profile)
        if not self.authenticated:
            raise PanelError('请先登录管理账号。')
        self.edition.check_action(action, payload)
        if action == 'edition.get':
            return self.edition.describe(self.account['id'])
        if action == 'edition.select-server':
            return self.select_free_server(payload)
        if action == 'logout':
            self.session().pop('delete_preview', None)
            self.authenticated, self.account, self.registry = (False, None, None)
            return {'authenticated': False}
        if action == 'account.get':
            return self.accounts.get_account(self.account['id'])
        if action == 'account.update':
            try:
                self.accounts.change_account(self.account['id'], payload.get('current_password'), payload.get('username'), payload.get('password'))
            except NativeAccountError as error:
                raise PanelError(str(error)) from None
            self.authenticated, self.account, self.registry = (False, None, None)
            return {'authenticated': False, 'message': '账号已更新，请使用新账号登录。'}
        if action in {'software.get', 'software.settings.get'}:
            values = self.software_settings(self.account)
            return values
        if action in {'software.update', 'software.settings.update'}:
            return self.update_software_settings(self.account, payload)
        if action == 'server.install.options':
            from native_server_install import discover_java
            from native_platform_install import options
            return {'platforms': options(), 'java_candidates': discover_java(), 'java_selection': 'archive-version-after-extraction' if payload.get('from_archive') is True else 'selected-minecraft-version'}
        if action == 'server.install.catalog.start':
            from native_server_install import platform_versions
            platform = str(payload.get('platform', ''))
            minecraft = str(payload.get('minecraft_version', '')) or None
            return self.component_job('install-catalog', None, lambda: platform_versions(platform, minecraft))
        if action == 'server.install.catalog.status':
            with self.pending_lock:
                return dict(self.component_jobs.get((self.account['id'], '', 'install-catalog'), {'active': False, 'error': '', 'result': {}}))
        if action == 'server.install.status':
            with self.install_lock:
                return dict(self.install_jobs.get(self.account['id'], {'active': False, 'phase': 'idle', 'progress': 0, 'message': '尚未开始安装。'}))
        if action == 'server.install.start':
            return self.start_server_install(payload)
        if action == 'server.archive.start':
            return self.start_server_install(payload, from_archive=True)
        if action == 'server.archive.preview':
            return self.start_archive_preview(payload)
        if action == 'server.archive.preview.clear':
            with self.install_lock:
                if self.install_jobs.get(self.account['id'], {}).get('active'):
                    raise PanelError('扫描或安装仍在进行，暂时不能清理预览。')
                preview = self.archive_previews.pop(self.account['id'], None)
            if preview is not None:
                preview.close()
            return {'message': '预览暂存已清理。'}
        if action == 'servers.list':
            return self.free_servers_list(self.account)
            if self.registry:
                result = self.registry.list_servers()
                return result
            try:
                result = self.read_registry(self.account)
            except PanelError:
                result = {'servers': [], 'active_server_id': ''}
            result['workspace_error'] = self.workspace_errors.get(self.account['id'], '')
            return result
        if action == 'servers.export':
            return {'schema': 1, 'servers': self.read_registry(self.account).get('servers', []), 'message': '仅导出当前账号的面板绑定信息，不包含服务器文件、账号密码或密钥。'}
        if action in {'servers.delete.preview', 'servers.delete'}:
            from native_server_delete import NativeServerDeletion
            deletion = NativeServerDeletion(self, ROOT)
            return deletion.preview(payload) if action.endswith('.preview') else deletion.delete(payload)
        if action == 'servers.remove' and (not False):
            return self.remove_free_binding(str(payload.get('id', '')))
        if action == 'servers.relocate':
            identifier = str(payload.get('id', ''))
            self.edition.require_server(self.account['id'], identifier)
            root = self.profile_root(self.account)
            file = root / 'data/servers.json'
            record = self.migration.read_json(file, {})
            original = next((item for item in record.get('servers', []) if item.get('id') == identifier), None)
            if not original:
                raise PanelError('指定的服务器不存在。')
            self.check_server_owner(str(payload.get('path', '')), self.account['id'])
            if self.registry:
                context = self.registry.get_context(identifier)
                if context.manager.server_pid() or self.busy():
                    raise PanelError('请先正常关闭目标服务器，并等待当前操作完成，再更改目录。')
            updated = ServerRegistry._validated_definition({**original, 'path': payload.get('path')})
            if any((item.get('id') != identifier and str(Path(item['path']).resolve()).casefold() == str(Path(updated['path']).resolve()).casefold() for item in record['servers'])):
                raise PanelError('这个服务器目录已经添加到当前工作区。')
            replacement = {**record, 'servers': [updated if item.get('id') == identifier else item for item in record['servers']]}
            self.migration.write_json(file, replacement)
            old = self.registries.pop(self.account['id'], None)
            if old:
                for context in old.contexts():
                    context.manager.stop_monitor()
            self.registry = self.safe_load_workspace(self.account)
            self.remember_portable_server(self.account, updated)
            return {'message': '服务器目录已更新，原有配置和任务保留。', 'workspace_error': self.workspace_errors.get(self.account['id'], '')}
        if action == 'servers.add':
            self.check_free_capacity()
            if self.workspace_errors.get(self.account['id']):
                raise PanelError('请先在服务器列表更改失效目录，再添加其他服务器。')
            self.check_server_owner(str(payload.get('path', '')), self.account['id'])
            if self.registry:
                definition = self.registry.add_server(payload)
                self.configure_manager(self.registry.get_context(definition['id']).manager, self.account['id'])
            else:
                raw = dict(payload)
                raw.setdefault('id', 'server-' + uuid.uuid4().hex[:8])
                server = Path(str(raw.get('path', '')))
                if not raw.get('launch_script'):
                    raw['launch_script'] = next((name for name in ('qizhang-server-run-once.bat', 'start-server.bat', 'run.bat', 'start.bat', 'start.cmd') if (server / name).is_file()), 'run.bat')
                raw['supports_watchdog'] = (server / 'qizhang-watchdog-launcher.ps1').is_file() and (server / 'qizhang-server-watchdog.py').is_file()
                definition = ServerRegistry._validated_definition(raw)
                root = self.prepare_workspace(self.account)
                (root / 'data').mkdir(exist_ok=True)
                self.migration.write_json(root / 'data/servers.json', {'version': 1, 'servers': [definition], 'active_server_id': definition['id']})
                self.edition.bind(self.account['id'], definition['id'])
                self.registry = self.load_workspace(self.account)
            self.remember_portable_server(self.account, definition)
            return {'server': definition, 'message': '服务器已添加。'}
        if action in {'servers.switch', 'servers.select'} and (not False):
            identifier = str(payload.get('server_id', payload.get('id', '')))
            self.edition.require_server(self.account['id'], identifier)
            if not self.registry:
                self.registry = self.safe_load_workspace(self.account)
            if not self.registry:
                raise PanelError(self.workspace_errors.get(self.account['id'], '管理槽位服务器暂不可用。'))
            return {'server': dict(self.registry.get_context(identifier).definition)}
        identifier = server_id or (self.edition.slot or {}).get('server_id', '')
        self.edition.require_server(self.account['id'], identifier)
        if not self.registry:
            if action == 'status' and self.workspace_errors.get(self.account['id']):
                return {'server': {'running': False, 'ready': False}, 'operation': {'active': False, 'message': '目录不可用，请到服务器列表更改目录。'}, 'workspace_error': self.workspace_errors[self.account['id']], 'panel': {'pid': os.getpid(), 'transport': 'stdio'}}
            raise PanelError('当前账号尚未添加服务器，请先在服务器页面添加或导入。')
        if action in {'servers.switch', 'servers.select'}:
            return {'server': self.registry.switch(payload.get('server_id', payload.get('id')))}
        context = self.registry.get_context(server_id or None)
        manager = context.manager
        if action == 'launch.settings':
            from native_launch_settings import inspect
            return inspect(manager, context.definition)
        if action == 'launch.alternatives':
            from native_startup_recovery import alternatives
            return alternatives(manager)
        if action == 'server.startup.clear_record':
            from native_startup_recovery import clear_closed_launcher_record
            return manager.run_direct_mutation(lambda: clear_closed_launcher_record(manager, payload))
        if action == 'launch.use_alternative':
            from native_startup_recovery import use_alternative
            registry = self.registry
            return manager.run_direct_mutation(lambda: use_alternative(manager, payload, lambda script: registry.set_launch_script(context.definition['id'], script)))
        if action == 'launch.save':
            from native_launch_settings import save
            registry = self.registry
            return manager.run_direct_mutation(lambda: save(manager, payload, context.definition, lambda script: registry.set_launch_script(context.definition['id'], script)))
        if action == 'server.eula.get':
            from native_platforms import profile as platform_profile
            if manager.platform_profile()['family'] != 'java':
                return {'required': False, 'accepted': True, 'url': 'https://www.minecraft.net/eula'}
            file = Path(context.definition['path']) / 'eula.txt'
            value = file.read_text(encoding='utf-8-sig') if file.is_file() else ''
            return {'accepted': bool(re.search('(?mi)^\\s*eula\\s*=\\s*true\\s*$', value)), 'url': 'https://www.minecraft.net/eula'}
        if action == 'server.eula.accept':
            if payload.get('accepted') is not True:
                raise PanelError('需要用户明确勾选同意 Minecraft EULA。')
            file = Path(context.definition['path']) / 'eula.txt'
            value = file.read_text(encoding='utf-8-sig') if file.is_file() else '# https://www.minecraft.net/eula\n'
            value = re.sub('(?mi)^\\s*eula\\s*=[^\\r\\n]*', 'eula=true', value) if re.search('(?mi)^\\s*eula\\s*=', value) else value + '\neula=true\n'
            temporary = file.with_name('eula.txt.qizhang-tmp')
            temporary.write_text(value, encoding='utf-8')
            temporary.replace(file)
            return {'accepted': True, 'message': '已记录你对此服务器的 EULA 同意。'}
        if action == 'status':
            result = manager.get_status()
            from native_connection_addresses import build_connection_addresses
            try:
                from native_platform_config import read_endpoint
                connection_properties = dict(manager.get_server_properties(), **read_endpoint(manager.server_root, manager.platform))
            except Exception:
                connection_properties = None
            tunnel_snapshot = None
            from native_platforms import profile as platform_profile
            result['server']['connection_addresses'] = build_connection_addresses(connection_properties, tunnel_snapshot)
            result['server']['connection_addresses']['network_protocol'] = manager.platform_profile()['network_protocol']
            result['server']['connection_addresses']['note'] += ' 网络协议：' + manager.platform_profile()['network_protocol'] + '。'
            result['selected_server'] = dict(context.definition)
            from native_platforms import profile as platform_profile
            result['platform_profile'] = manager.platform_profile()
            from native_diagnostics import command_channel
            result['server']['command_channel'] = command_channel(manager, result['server'])
            result['panel'] = {'pid': os.getpid(), 'uptime_seconds': int(time.monotonic() - self.started), 'transport': 'stdio'}
            return result
        if action == 'diagnostics.preview':
            from native_diagnostics import collect
            document = collect(manager, context.definition, VERSION, payload.get('include_logs', False))
            token = secrets.token_urlsafe(24)
            self._diagnostic_preview = (self.account['id'], context.definition['id'], token, time.monotonic(), document)
            return {**document, 'preview_token': token, 'preview_text': json.dumps(document['report'], ensure_ascii=False, indent=2) + '\n\n' + document['logs']}
        if action == 'diagnostics.export':
            preview = self._diagnostic_preview
            if not preview or preview[:2] != (self.account['id'], context.definition['id']) or (not secrets.compare_digest(preview[2], str(payload.get('preview_token', '')))) or (time.monotonic() - preview[3] > 900):
                raise PanelError('诊断预览已失效，请重新预览后导出。')
            from native_diagnostics import archive
            result = archive(preview[4])
            self._diagnostic_preview = None
            return result
        if action == 'server.action':
            return {'message': manager.request_server_action(str(payload.get('action', '')))}
        if action == 'countdown.start':
            restart = payload.get('restart_after', False)
            if not isinstance(restart, bool):
                raise PanelError('重启选项格式无效。')
            result = manager.start_shutdown_countdown(payload.get('seconds', 60))
            if restart:
                worker = manager._shutdown_countdown_thread

                def after_countdown():
                    if worker:
                        worker.join()
                    status = manager.get_status()
                    if status.get('shutdown_countdown', {}).get('phase') == 'completed' and (not manager.validated_server_pid()):
                        manager.request_server_action('start')
                self.async_job((self.account['id'], context.definition['id'], 'countdown-restart'), after_countdown, manager)
            return {'countdown': result, 'message': '已发送停服通知。'}
        if action == 'countdown.cancel':
            return {'countdown': manager.cancel_shutdown_countdown(), 'message': '正在取消停服通知。'}
        if action == 'logs':
            return {'lines': manager.get_logs(int(payload.get('lines', 200)), str(payload.get('q', '')), str(payload.get('level', '')))}
        if action == 'logs.poll':
            from native_monitoring import for_manager
            return for_manager(manager).poll_logs(payload.get('cursor'), payload.get('lines', 200), payload.get('q', ''), payload.get('level', ''))
        if action == 'monitoring.metrics':
            from native_monitoring import for_manager
            return for_manager(manager).metrics()
        if action == 'command':
            manager.run_direct_mutation(lambda: manager.send_command(str(payload.get('command', ''))))
            from native_diagnostics import command_channel
            return {'message': '命令已提交；执行结果请查看服务器本次日志。', 'execution_confirmed': False, 'command_channel': command_channel(manager, manager.get_status().get('server', {}))}
        if action == 'settings.get':
            result = manager.get_settings()
            result['capabilities']['watchdog'] = bool(result['capabilities'].get('watchdog') and False)
            result['selected_server'] = dict(context.definition)
            from native_platforms import profile as platform_profile
            result['platform_profile'] = manager.platform_profile()
            preferences = self.software_settings(self.account)
            for key in ('port', 'bind', 'remote_access', 'open_browser', 'auto_start_panel'):
                result['panel'].pop(key, None)
            result['panel'] = {key: value for key, value in result['panel'].items() if key == 'poll_seconds'}
            result['capabilities']['watchdog'] = False
            return result
        if action == 'settings.capabilities':
            snapshot = manager.get_status()
            state = snapshot.get('server', {})
            editable = bool(state) and state.get('status_known') is not False and (not state.get('status_stale')) and (not state.get('running')) and (not state.get('starting')) and (not snapshot.get('operation', {}).get('active')) and (not snapshot.get('shutdown_countdown', {}).get('active')) and (not manager.starting_flag_path.exists()) and (not manager.maintenance_flag_path.exists())
            from native_platforms import profile as platform_profile
            return {'platform_profile': manager.platform_profile(), 'capabilities': {'server_endpoint_editable': bool(editable), 'server_endpoint_lock_reason': '' if editable else '服务器尚未完全停止，或监控状态不确定。', 'watchdog': bool(manager.supports_watchdog and False)}}
        if action == 'settings.update':
            options = payload.get('panel', {})
            if not isinstance(options, dict):
                raise PanelError('服务器设置格式无效。')
            if 'auto_start_panel' in options:
                raise PanelError('面板开机启动请在右上角软件设置中修改。')
            if any((key in options for key in ('remote_password', 'remote_username', 'bind', 'port', 'remote_access', 'open_browser'))):
                raise PanelError('独立版不使用网页访问设置；账号请在账号页面修改。')

            def update_server_settings():
                self.check_registered_endpoint(manager, payload.get('server_properties', {}))
                return manager.update_settings(payload)
            message = manager.run_direct_mutation(update_server_settings)
            return {'message': message}
        if action == 'backups.list':
            return {'backups': manager.list_backups()}
        if action == 'backups.create':
            return {'message': manager.request_server_action('backup', backup_mode=payload.get('mode'))}
        if action == 'backups.restore':
            restart = payload.get('restart_after', True)
            if not isinstance(restart, bool):
                raise PanelError('重启选项格式无效。')
            return {'message': manager.request_restore_backup(str(payload.get('filename', '')), str(payload.get('confirm', '')), restart)}
        if action == 'backups.delete':
            manager.run_direct_mutation(lambda: manager.delete_backup(str(payload.get('filename', ''))))
            return {'message': '备份已删除。'}
        raise PanelError('无法识别的操作。')

    def close(self):
        if getattr(self, 'exit_controller', None):
            self.exit_controller.close()
        for preview in getattr(self, 'archive_previews', {}).values():
            preview.close()
        self.archive_previews.clear()
        for registry in self.registries.values():
            for context in registry.contexts():
                context.manager.stop_monitor()
        self.registries.clear()
        self.registry = None
        state = self.migration.read_json(self.root / 'native-state.json', {})
        if state.get('pid') == os.getpid():
            (self.root / 'native-state.json').unlink(missing_ok=True)
        self.lock.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'QiZhangPanel-Free')
    
    parser.add_argument('--autostart', action='store_true')
    args = parser.parse_args()
    import io
    stream_in = sys.stdin or io.TextIOWrapper(open(0, 'rb', closefd=False), encoding='utf-8')
    stream_out = sys.stdout or io.TextIOWrapper(open(1, 'wb', closefd=False), encoding='utf-8', write_through=True)
    stream_err = sys.stderr or io.TextIOWrapper(open(2, 'wb', closefd=False), encoding='utf-8', write_through=True)
    for stream in (stream_in, stream_out, stream_err):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    host = None
    failure = None
    with contextlib.redirect_stdout(stream_err), contextlib.redirect_stderr(stream_err):
        try:
            host = NativeHost(args.data_root, autostart=args.autostart)
        except Exception as error:
            failure = str(error)
            traceback.print_exc(file=stream_err)
        try:
            first_frame = True
            while True:
                line = stream_in.readline(1024 * 1024 + 1)
                if not line:
                    break
                if first_frame:
                    line = line.removeprefix('\ufeff')
                    first_frame = False
                request = {}
                try:
                    if len(line) > 1024 * 1024:
                        raise PanelError('请求内容过大。')
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        request = {}
                        raise PanelError('请求格式无效。')
                    if failure:
                        raise PanelError(failure)
                    data = host.request(str(request.get('action', '')), request.get('payload') or {}, str(request.get('server_id') or ''))
                    response = {'id': request.get('id'), 'ok': True, 'data': data}
                except Exception as error:
                    response = {'id': request.get('id'), 'ok': False, 'error': str(error)}
                stream_out.write(json.dumps(response, ensure_ascii=False, separators=(',', ':')) + '\n')
                stream_out.flush()
                if host and host.exiting:
                    break
        finally:
            if host:
                host.close()
    return 1 if failure else 0
if __name__ == '__main__':
    raise SystemExit(main())
