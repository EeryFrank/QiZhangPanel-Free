# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Owned direct native/PHP startup. Import never executes package programs."""
import json
import os
from pathlib import Path
import re
import uuid
from native_platforms import profile

CONFIG = 'qizhang-platform-launch.json'
LAUNCHER = 'qizhang-platform-start.bat'
SCRIPT = 'qizhang-platform-start.ps1'
BATCH = '@echo off\nsetlocal DisableDelayedExpansion\ncd /d "%~dp0"\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qizhang-platform-start.ps1"\nexit /b %errorlevel%\n'
PS_SCRIPT = '''$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'qizhang-platform-launch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = $cfg.runtime_path
if (-not [System.IO.Path]::IsPathRooted($runtime)) { $runtime = Join-Path $PSScriptRoot $runtime }
$launchArgs = @($cfg.runtime_args)
if ($cfg.kind -eq 'php') { $launchArgs += @((Join-Path $PSScriptRoot $cfg.entry)) }
$launchArgs += @($cfg.server_args)
& $runtime @launchArgs
exit $LASTEXITCODE
'''


def _error(message):
    from server_manager import PanelError
    return PanelError(message)


def _checked(path, *, exists=True):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise _error('启动文件及运行时路径不能包含符号链接或目录联接。')
    if exists and not path.is_file():
        raise _error('启动文件或运行时不存在：' + str(path))
    return path


def _args(value, label):
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if not isinstance(value, list) or len(value) > 128 or any(
            not isinstance(item, str) or not item or len(item) > 4096 or any(ord(c) < 32 for c in item)
            for item in value):
        raise _error(label + '须为每行一个参数，最多 128 项，不能包含控制字符。')
    return list(value)


def validate(root, config, *, platform=None, server_id=None):
    root = Path(root).resolve()
    cfg = dict(config)
    if type(cfg.get('schema')) is not int or cfg['schema'] != 1:
        raise _error('平台启动配置版本无效。')
    spec = profile(cfg.get('platform'))
    if spec['runtime'] not in {'native', 'php'} or cfg.get('kind') != spec['runtime']:
        raise _error('该平台不能使用原生/PHP启动配置。')
    if platform and spec['id'] != platform:
        raise _error('平台启动配置与登记的平台不一致。')
    if cfg.get('server_id') and server_id is not None and cfg['server_id'] != server_id:
        raise _error('平台启动配置与登记的实例不一致。')
    entry = Path(str(cfg.get('entry', '')))
    expected = 'bedrock_server.exe' if spec['runtime'] == 'native' else 'pocketmine-mp.phar'
    if entry.is_absolute() or entry.name.lower() != expected or not (root / entry).resolve().is_relative_to(root):
        raise _error('启动入口必须是服务器目录内对应平台的官方可执行文件/PHAR。')
    _checked(root / entry)
    runtime = Path(str(cfg.get('runtime_path') or (entry if spec['runtime'] == 'native' else '')))
    if not str(cfg.get('runtime_path', '')) and spec['runtime'] == 'php':
        raise _error('未找到 PHP 运行时，请选择与 PocketMine 版本匹配的 php.exe。')
    if not runtime.is_absolute():
        runtime = root / runtime
        if not runtime.resolve().is_relative_to(root):
            raise _error('相对运行时路径不能超出服务器目录。')
    _checked(runtime)
    if spec['runtime'] == 'native' and runtime.resolve() != (root / entry).resolve():
        raise _error('基岩版运行程序必须与导入的 bedrock_server.exe 一致。')
    if spec['runtime'] == 'php' and runtime.name.lower() != 'php.exe':
        raise _error('PocketMine 运行时必须选择 php.exe；不能使用 Java。')
    cfg.update(entry=entry.as_posix(), runtime_path=str(runtime.resolve()),
               runtime_args=_args(cfg.get('runtime_args', []), '运行时参数'),
               server_args=_args(cfg.get('server_args', []), '服务端参数'))
    return cfg


def read(root, **kwargs):
    path = _checked(Path(root) / CONFIG)
    if path.stat().st_size > 128 * 1024:
        raise _error('平台启动配置文件过大。')
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg, dict):
        raise _error('平台启动配置格式无效。')
    return validate(root, cfg, **kwargs)


def write(root, platform, entry, runtime_path='', runtime_args=None, server_args=None, server_id=''):
    from server_manager import atomic_write_json, atomic_write_text
    root = Path(root).resolve()
    spec = profile(platform)
    if server_id and not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', server_id):
        raise _error('实例标识无效。')
    from native_platform_templates import receipt as template_receipt
    cfg = validate(root, dict(schema=1, platform=platform, platform_template=template_receipt(platform), kind=spec['runtime'], entry=str(entry),
                             runtime_path=str(runtime_path), runtime_args=[] if runtime_args is None else runtime_args,
                             server_args=[] if server_args is None else server_args, server_id=server_id))
    runtime = Path(cfg['runtime_path'])
    if runtime.is_relative_to(root):
        cfg['runtime_path'] = runtime.relative_to(root).as_posix()
    for name in (CONFIG, LAUNCHER, SCRIPT):
        _checked(root / name, exists=False)
    atomic_write_json(root / CONFIG, cfg)
    atomic_write_text(root / SCRIPT, PS_SCRIPT, 'utf-8-sig')
    atomic_write_text(root / LAUNCHER, BATCH, 'utf-8')
    return dict(launch_script=LAUNCHER, config_file=CONFIG, platform=platform, entry=cfg['entry'])


def build_launch(manager):
    if manager.launch_script != LAUNCHER:
        return None
    root = manager.server_root
    if (_checked(root / LAUNCHER).read_text(encoding='utf-8-sig') != BATCH or
            _checked(root / SCRIPT).read_text(encoding='utf-8-sig') != PS_SCRIPT):
        raise _error('面板平台启动脚本已修改，请重新保存启动设置；未自动执行变更后的脚本。')
    cfg = read(root, platform=manager.platform, server_id=manager.server_id)
    arguments = [cfg['runtime_path'], *cfg['runtime_args']]
    if cfg['kind'] == 'php':
        arguments.append(str((root / cfg['entry']).resolve()))
    arguments.extend(cfg['server_args'])
    environment = os.environ.copy()
    environment['QIZHANG_SERVER_ROOT'] = str(root.resolve())
    return arguments, environment


def inspect(manager):
    spec = profile(manager.platform, manager.server_root)
    try:
        cfg = read(manager.server_root, platform=manager.platform, server_id=manager.server_id)
        return dict(cfg, supported=True, platform_profile=spec, runtime=spec['runtime'],
                    java_applicable=False, launch_script=manager.launch_script,
                    message='运行时参数与服务端参数均为每行一项；仅停服后允许保存。入口文件只读，原文件保留。')
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        return dict(supported=False, platform_profile=spec, runtime=spec['runtime'], java_applicable=False,
                    launch_script=manager.launch_script, message=str(error))


def process_snapshot(manager):
    """Native/PHP liveness with exact entry evidence, unknown remains unknown."""
    from native_managed_launch import _native_process_rows, owned_process_pid
    try:
        owned = owned_process_pid(manager)
        if owned:
            return dict(java_pid=owned, launcher_pids=[], watchdog_pids=[])
        cfg = read(manager.server_root, platform=manager.platform, server_id=manager.server_id)
        entry = str((manager.server_root / cfg['entry']).resolve()).replace('/', '\\').lower()
        launcher = str(manager.server_root / LAUNCHER).replace('/', '\\').lower()
        script = str(manager.server_root / SCRIPT).replace('/', '\\').lower()
        expected_image = 'bedrock_server.exe' if cfg['kind'] == 'native' else 'php.exe'
        result = dict(java_pid=0, launcher_pids=[], watchdog_pids=[])
        for row in _native_process_rows():
            if row.get('exited'):
                continue
            command = row.get('command', '').replace('/', '\\').lower()
            if row['name'] == expected_image:
                if not command:
                    return None
                exact_native = False
                if cfg['kind'] == 'native':
                    image = manager.process_image_name(row['pid'])
                    if not image:
                        return None
                    exact_native = Path(image).resolve() == Path(cfg['runtime_path']).resolve()
                if exact_native or re.search(r'(?:^|[\s"])' + re.escape(entry) + r'(?=$|[\s"])', command):
                    if result['java_pid']:
                        return None
                    result['java_pid'] = row['pid']
                elif row['name'] == 'php.exe' and 'pocketmine-mp.phar' in command:
                    # A relative PHAR in a shared PHP cannot establish its cwd.
                    return None
            elif launcher in command or script in command:
                result['launcher_pids'].append(row['pid'])
        return result
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        return None


def save(manager, payload, persist_launcher=None):
    with manager._shutdown_countdown_lock, manager._operation_lock:
        reason = manager._server_endpoint_lock_reason(force=True)
        if reason:
            raise _error(reason)
        current = read(manager.server_root, platform=manager.platform, server_id=manager.server_id)
        if any(key in payload for key in ('entry', 'kind', 'platform', 'jvm_args', 'java_path')):
            raise _error('不能通过运行时设置改写平台、入口或 Java 参数。')
        targets = [_checked(manager.server_root / name) for name in (CONFIG, SCRIPT, LAUNCHER)]
        previous = {path: path.read_bytes() for path in targets}
        try:
            result = write(manager.server_root, manager.platform, current['entry'],
                           payload.get('runtime_path', current['runtime_path']),
                           _args(payload.get('runtime_args', current['runtime_args']), '运行时参数'),
                           _args(payload.get('server_args', current['server_args']), '服务端参数'), manager.server_id)
            if persist_launcher is not None:
                persist_launcher(LAUNCHER)
        except Exception:
            for path, content in previous.items():
                # Atomic replacement avoids a truncated executable configuration.
                temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.restore.tmp')
                _checked(temporary, exists=False)
                temporary.write_bytes(content)
                os.replace(temporary, path)
            raise
        manager.launch_script = LAUNCHER
        return dict(result, message='平台启动设置已保存，下次启动生效；原启动文件保留。')
