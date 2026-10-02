# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from server_manager import PanelError, ServerManager, atomic_write_json, read_json
SERVER_ID_RE = re.compile('^[a-z0-9][a-z0-9_-]{0,31}$')
from native_platforms import PLATFORMS, profile as platform_profile
SERVER_PLATFORMS = set(PLATFORMS)
GLOBAL_CONFIG_KEYS = ('poll_seconds',)

@dataclass
class ServerContext:
    definition: dict[str, Any]
    manager: ServerManager

class ServerRegistry:
    """Owns the panel's independent per-server managers and active selection."""

    def __init__(self, panel_root: Path, default_server_root: Path, *, runtime_policy=None, managed_server_id: str | None=None) -> None:
        self.runtime_policy = runtime_policy
        self.managed_server_id = managed_server_id
        self.panel_root = panel_root.resolve()
        self.data_root = self.panel_root / 'data'
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.data_root / 'servers.json'
        self.global_config_path = self.data_root / 'panel-config.json'
        self._lock = threading.RLock()
        self._contexts: dict[str, ServerContext] = {}
        self._registry = self._load_registry(default_server_root.resolve())
        self._global_config = self._load_global_config()
        self._build_contexts()

    def _load_registry(self, default_root):
        value = read_json(self.registry_path, None)
        if not isinstance(value, dict) or not isinstance(value.get('servers'), list):
            raise PanelError('服务器列表无法读取，已保留原文件。')
        if not any((item.get('id') == self.managed_server_id for item in value['servers'])):
            raise PanelError('单服务器绑定对应的服务器不存在。')
        return {**value, 'active_server_id': self.managed_server_id}

    def _load_global_config(self) -> dict[str, Any]:
        raw = read_json(self.global_config_path, {})
        defaults = json.loads(json.dumps(ServerManager.DEFAULT_PANEL_CONFIG))
        if isinstance(raw, dict):
            for key in GLOBAL_CONFIG_KEYS:
                if key in raw:
                    defaults[key] = raw[key]
        return defaults

    @staticmethod
    def _validated_definition(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise PanelError('服务器配置格式无效。')
        server_id = str(raw.get('id', '')).strip().lower()
        if not SERVER_ID_RE.fullmatch(server_id):
            raise PanelError('服务器标识只能使用小写字母、数字、横线和下划线。')
        name = str(raw.get('name', '')).strip()
        if not 1 <= len(name) <= 40:
            raise PanelError('服务器名称长度必须为 1～40 个字符。')
        platform = str(raw.get('platform', 'neoforge')).strip().lower()
        if platform not in SERVER_PLATFORMS:
            raise PanelError('服务端平台标识不受支持，请从平台列表选择。')

        def version_text(key: str, label: str) -> str:
            value = str(raw.get(key, '')).strip()
            if len(value) > 80:
                raise PanelError(f'{label}不能超过 80 个字符。')
            return value
        minecraft_version = version_text('minecraft_version', 'Minecraft 版本')
        loader_version = version_text('loader_version', '加载器版本')
        content_version = version_text('content_version', '整合包/核心模组版本')
        path = Path(str(raw.get('path', '')).strip()).expanduser()
        if not path.is_absolute():
            raise PanelError('服务器目录必须使用完整绝对路径。')
        path = path.resolve()
        if not path.is_dir():
            raise PanelError('服务器目录不存在。')
        launch_script = str(raw.get('launch_script', 'qizhang-server-run-once.bat')).strip()
        if not launch_script or Path(launch_script).name != launch_script or Path(launch_script).suffix.lower() not in {'.bat', '.cmd'}:
            raise PanelError('启动脚本必须是服务器根目录中的 .bat/.cmd 文件。')
        if not (path / launch_script).is_file():
            raise PanelError(f'找不到启动脚本：{path / launch_script}')
        if platform_profile(platform)['runtime'] in {'native', 'php'}:
            from native_platform_launch import read, LAUNCHER
            if launch_script != LAUNCHER:
                raise PanelError('原生/PHP平台须使用面板生成的直接启动入口。')
            read(path, platform=platform, server_id=server_id)
        elif not (path / 'server.properties').is_file():
            from native_server_archive import detect_core
            if detect_core(path) is None:
                raise PanelError('缺少配置且未识别到可验证的服务端入口。')
        control_raw = raw.get('control_script')
        control_script = str(control_raw).strip() if control_raw else None
        if control_script and (Path(control_script).name != control_script or Path(control_script).suffix.lower() != '.ps1'):
            raise PanelError('控制脚本必须是服务器根目录中的 .ps1 文件。')
        if control_script and (not (path / control_script).is_file()):
            control_script = None
        supports_watchdog = bool(raw.get('supports_watchdog', False))
        if supports_watchdog and (not ((path / 'qizhang-watchdog-launcher.ps1').is_file() and (path / 'qizhang-server-watchdog.py').is_file())):
            supports_watchdog = False
        try:
            default_voice_port = 24453 if server_id == 'test-vnext' else 24454
            voice_port = int(raw.get('voice_port', default_voice_port))
        except (TypeError, ValueError):
            raise PanelError('语音端口必须是 1～65535 的整数。') from None
        if not 1 <= voice_port <= 65535:
            raise PanelError('语音端口必须是 1～65535 的整数。')
        return {'id': server_id, 'name': name, 'platform': platform, 'minecraft_version': minecraft_version, 'loader_version': loader_version, 'content_version': content_version, 'path': str(path), 'launch_script': launch_script, 'control_script': control_script, 'supports_watchdog': supports_watchdog, 'voice_port': voice_port}

    def _server_data_root(self, server_id: str) -> Path:
        return self.data_root / 'servers' / server_id

    def _migrate_legacy_data(self, server_id: str, target: Path) -> None:
        if server_id != 'formal':
            return
        for filename in ('panel-config.json',):
            source = self.data_root / filename
            destination = target / filename
            if source.is_file() and (not destination.exists()):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

    def _build_context(self, definition):
        server_id = definition['id']
        context_root = self._server_data_root(server_id)
        self._migrate_legacy_data(server_id, context_root)
        manager = ServerManager(Path(definition['path']), self.panel_root, server_id=server_id, data_root=context_root, platform=definition['platform'], launch_script=definition['launch_script'], control_script=definition['control_script'], supports_watchdog=False, voice_port=definition['voice_port'], runtime_policy=self.runtime_policy)
        return ServerContext(definition, manager)

    def _build_contexts(self) -> None:
        for definition in self._registry['servers']:
            if self.runtime_policy is not None and (not False):
                if definition['id'] != self.managed_server_id:
                    continue
                definition = self._validated_definition(definition)
            context = self._build_context(definition)
            self._contexts[definition['id']] = context

    @property
    def active_server_id(self) -> str:
        with self._lock:
            return str(self._registry['active_server_id'])

    @property
    def active(self) -> ServerContext:
        return self.get_context()

    def get_context(self, server_id: str | None=None) -> ServerContext:
        """Resolve one request without changing the legacy global selection."""
        with self._lock:
            candidate = self._registry['active_server_id'] if server_id is None else str(server_id).strip().lower()
            context = self._contexts.get(candidate)
            if context is None:
                raise PanelError('指定的服务器不存在。')
            return context

    @property
    def manager(self) -> ServerManager:
        return self.active.manager

    @property
    def global_manager(self) -> ServerManager:
        return self._contexts[next(iter(self._contexts))].manager

    def contexts(self) -> list[ServerContext]:
        with self._lock:
            return list(self._contexts.values())

    def set_launch_script(self, server_id: str, launch_script: str) -> None:
        with self._lock:
            context = self.get_context(server_id)
            definition = self._validated_definition({**context.definition, 'launch_script': launch_script})
            document = {**self._registry, 'servers': [definition if item['id'] == server_id else item for item in self._registry['servers']]}
            atomic_write_json(self.registry_path, document)
            self._registry = document
            context.definition.update(definition)
            context.manager.launch_script = launch_script

    def list_servers(self) -> dict[str, Any]:
        with self._lock:
            active = self._registry['active_server_id']
            contexts = list(self._contexts.values())
        servers: list[dict[str, Any]] = []
        for context in contexts:
            snapshot = context.manager.get_status()
            status = snapshot.get('server', {})
            definition = dict(context.definition)
            definition.update({'active': definition['id'] == active, 'platform_profile': context.manager.platform_profile(), 'running': bool(status.get('running')), 'starting': bool(status.get('starting')), 'ready': bool(status.get('ready')), 'state': status.get('state', 'unknown'), 'status_known': bool(status.get('status_known')), 'status_stale': bool(status.get('status_stale', True)), 'updated_at': status.get('updated_at', ''), 'monitor_error': status.get('monitor_error', ''), 'operation': snapshot.get('operation', {}), 'shutdown_countdown': snapshot.get('shutdown_countdown', {}), 'port': status.get('port') or context.manager.get_server_properties().get('server-port', str(platform_profile(definition['platform'])['default_port'])), 'command_agent': (context.manager.command_agent_root / 'qizhang-command-agent.jar').is_file()})
            servers.append(definition)
        return {'active_server_id': active, 'servers': servers}

    def switch(self, server_id: Any) -> dict[str, Any]:
        candidate = str(server_id or '').strip().lower()
        with self._lock:
            if candidate not in self._contexts:
                raise PanelError('指定的服务器不存在。')
            self._registry['active_server_id'] = candidate
            atomic_write_json(self.registry_path, self._registry)
            definition = dict(self._contexts[candidate].definition)
        return definition

    def remove_server(self, server_id: Any) -> dict[str, Any]:
        candidate = str(server_id or '').strip().lower()
        with self._lock:
            if candidate == self._registry['active_server_id']:
                raise PanelError('不能删除当前选中的服务器，请先切换到另一台。')
            context = self._contexts.get(candidate)
            if context is None:
                raise PanelError('指定的服务器不存在。')
            if context.manager.get_status().get('operation', {}).get('active'):
                raise PanelError('这台服务器有操作正在执行，暂时不能移除。')
            self._contexts.pop(candidate)
            self._registry['servers'] = [item for item in self._registry['servers'] if item['id'] != candidate]
            atomic_write_json(self.registry_path, self._registry)
        context.manager.stop_monitor()
        return dict(context.definition)

    def finalize_deleted_server(self, server_id: str) -> str:
        """Commit only after the exact server folder has actually disappeared.

        Permanent deletion owns the lifecycle locks and stopped the workers.
        Unlike unbinding, this supports deleting the active or final server.
        Write first so a failed registry write retains the in-memory binding.
        """
        with self._lock:
            context = self._contexts.get(server_id)
            if context is None:
                raise PanelError('待删除服务器的绑定已改变。')
            if Path(context.definition['path']).exists():
                raise PanelError('服务器文件夹仍存在，不会先移除绑定。')
            remaining = [item for item in self._registry['servers'] if item['id'] != server_id]
            active = self._registry.get('active_server_id', '')
            if active == server_id or active not in {item['id'] for item in remaining}:
                active = remaining[0]['id'] if remaining else ''
            replacement = {**self._registry, 'servers': remaining, 'active_server_id': active}
            atomic_write_json(self.registry_path, replacement)
            self._registry = replacement
            self._contexts.pop(server_id)
            return active
