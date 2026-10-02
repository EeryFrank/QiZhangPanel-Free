# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Materialize official Forge files for two verified installer-style templates.

Pack scripts are data only. Their downloaders, Java managers, cleanup hooks,
ServerStarterJar and restart loops are never run. Existing files are never
overwritten. This module does not start Minecraft or accept its EULA.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import shutil
import uuid


class BootstrapError(RuntimeError):
    pass


ATM_TEMPLATE = '020947e110971205271548ce5581b4099fac40e766bc8d8704942492e90146bc'
SPC_BAT_TEMPLATE = '45a2a53fd195d65b2d93c44585085c26e10c1b00b9aa0b573a3bafd5f19b5e91'
SPC_PS1_TEMPLATE = '2d16c912a25ed94a763b2b795a90483316cdf329fb3a04283308ba30fa4f6cce'
EXCLUDED = {'mods', 'config', 'defaultconfigs', 'libraries', 'backups', 'world', 'runtime', '.minecraft', 'versions'}


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _checked(root, path, *, existing=True):
    root, path = Path(root).resolve(), Path(path)
    if not path.resolve().is_relative_to(root):
        raise BootstrapError('初始化文件路径越界。')
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise BootstrapError('初始化路径含有链接，未执行安装。')
    if existing and not path.is_file():
        raise BootstrapError('初始化文件不存在：' + path.name)
    return path


def _text(root, name, limit=128 * 1024):
    path = _checked(root, Path(root) / name)
    if path.stat().st_size > limit:
        raise BootstrapError('初始化配置过大：' + name)
    data = path.read_bytes()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('gb18030')
    if '\0' in text:
        raise BootstrapError('初始化配置含无效字符。')
    record = {'path': name, 'sha256': hashlib.sha256(data).hexdigest(),
              'format': path.suffix.lower().lstrip('.'), 'can_run_original': False,
              'blocked_reason': '此初始化脚本会自动下载、清理或循环重启；仅保留原文件，需使用面板专属启动。'}
    return text, record


def _fingerprint(text):
    normalized = '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').replace('\r', '\n').splitlines()).strip() + '\n'
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _variables(text):
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'\s*([A-Z][A-Z0-9_]*)\s*=(.*)', line)
        if not match or match[1] in result:
            raise BootstrapError('variables.txt 含重复或无法确认的配置行。')
        value = match[2].strip()
        if value.startswith('"'):
            if len(value) < 2 or not value.endswith('"'):
                raise BootstrapError('variables.txt 配置引号未闭合。')
            value = value[1:-1]
        result[match[1]] = value
    return result


def _arguments(text):
    from native_startup_import import _cmd_tokens, _check_arguments, StartupParseError
    if any(char in text for char in '$%`\r\n'):
        raise BootstrapError('初始化参数包含动态表达式，不能自动适配。')
    try:
        values = _cmd_tokens(text)
        _check_arguments(values, [])
    except StartupParseError as error:
        raise BootstrapError(str(error)) from None
    return values


def _existing_jvm(root):
    matches = [p for p in root.iterdir() if p.name.casefold() == 'user_jvm_args.txt']
    if len(matches) > 1:
        raise BootstrapError('存在大小写冲突的 JVM 参数文件。')
    if not matches:
        return None, None
    from native_startup_import import _jvm_argument_file, _check_arguments, StartupParseError
    try:
        args, record = _jvm_argument_file(root, '@' + matches[0].name)
        _check_arguments(args, [])
    except (OSError, ValueError, StartupParseError) as error:
        raise BootstrapError('无法完整保留原 JVM 参数：' + str(error)) from None
    return args, record


def _atm(root):
    path = root / 'startserver.bat'
    if not path.is_file():
        return None
    text, record = _text(root, path.name)
    if 'ATM9_INSTALL_ONLY' not in text or 'FORGE_URL' not in text:
        return None
    versions = re.findall(r'(?m)^set FORGE_VERSION=(\d+\.\d+\.\d+)\s*$', text)
    if len(versions) != 1 or not versions[0].startswith('47.'):
        raise BootstrapError('ATM 初始化脚本的 Forge 版本不是唯一字面值。')
    canonical = re.sub(r'(?m)^set FORGE_VERSION=\d+\.\d+\.\d+\s*$', 'set FORGE_VERSION={FORGE_VERSION}', text)
    if _fingerprint(canonical) != ATM_TEMPLATE:
        raise BootstrapError('ATM 初始化脚本与已验证模板不同，不能忽略其中的自定义操作。')
    args, argument_file = _existing_jvm(root)
    return {'template': 'atm9-forge-1.20.1', 'minecraft_version': '1.20.1', 'loader_version': versions[0],
            'java_major': 17, 'source': record, 'source_records': [record] + ([argument_file] if argument_file else []), 'original_scripts': [record],
            'jvm_args': args, 'argument_files': [argument_file] if argument_file else [],
            'game_args': ['nogui'], 'java_hint': 'java', 'java_hint_kind': 'path',
            'default_properties': {'allow-flight': 'true', 'motd': 'All the Mods 9', 'max-tick-time': '180000'},
            'warnings': ['原 ATM 自动重启循环保留在原文件中；面板专属启动不执行该循环。']}


def _spc(root):
    if not all((root / name).is_file() for name in ('manifest.json', 'variables.txt', 'start.bat', 'start.ps1')):
        return None
    text, manifest_record = _text(root, 'manifest.json', 2 * 1024 * 1024)
    try:
        manifest = json.loads(text)
    except ValueError:
        return None
    if not isinstance(manifest, dict) or str(manifest.get('serverPackCreatorVersion')) != '8.1.2':
        return None
    batch, batch_record = _text(root, 'start.bat')
    powershell, ps_record = _text(root, 'start.ps1')
    if _fingerprint(batch) != SPC_BAT_TEMPLATE or _fingerprint(powershell) != SPC_PS1_TEMPLATE:
        raise BootstrapError('ServerPackCreator 初始化脚本与已验证的 8.1.2 模板不同，未执行脚本。')
    variable_text, variable_record = _text(root, 'variables.txt')
    values = _variables(variable_text)
    mc, loader = values.get('MINECRAFT_VERSION'), values.get('MODLOADER_VERSION')
    if (mc != '1.20.1' or values.get('MODLOADER', '').lower() != 'forge'
            or not re.fullmatch(r'47\.\d+\.\d+', loader or '')
            or values.get('RECOMMENDED_JAVA_VERSION') != '17'
            or manifest.get('minecraftVersion') != mc
            or str(manifest.get('modloader', '')).lower() != 'forge'
            or manifest.get('modloaderVersion') != loader):
        raise BootstrapError('ServerPackCreator 清单与变量中的 Minecraft/Forge/Java 版本不一致或暂不支持。')
    # ConvertFrom-StringData unescapes backslashes before upstream tokenization.
    # This bounded adapter must not silently preserve a different literal value.
    for field in ('JAVA_ARGS', 'ADDITIONAL_ARGS', 'SSJ_FORGE_ARGS'):
        if '\\' in values.get(field, ''):
            raise BootstrapError(field + ' 含 PowerShell 反斜线转义，暂不能保证原参数语义，未自动适配。')
    args = _arguments(values.get('ADDITIONAL_ARGS', '')) + _arguments(values.get('JAVA_ARGS', ''))
    if values.get('USE_SSJ') not in {'true', 'false'}:
        raise BootstrapError('USE_SSJ 必须是明确的 true/false。')
    if values['USE_SSJ'] == 'true':
        args += _arguments(values.get('SSJ_FORGE_ARGS', ''))
    original_args, original_record = _existing_jvm(root)
    # This exact upstream template rewrites user_jvm_args from JAVA_ARGS at each
    # launch. Preserve that effective behavior in the dedicated panel file,
    # while leaving any original JVM file byte-for-byte intact.
    warning = ['保留 ServerPackCreator 的堆内存与 JVM 参数；不运行 SSJ/Jabba 下载、清理和循环重启。']
    if original_record:
        warning.append('原模板每次从 variables.txt 重建 JVM 参数；面板读取相同变量，已有 JVM 文件原样保留。')
    java = values.get('JAVA', 'java')
    if java.lower() not in {'java', 'java.exe'}:
        # ConvertFrom-StringData has PowerShell-specific path escaping. Do not
        # reinterpret such values with a shell or silently choose another JVM.
        raise BootstrapError('此模板的 JAVA 使用了自定义路径；暂不能保证原路径转义语义，未自动替换 Java。')
    return {'template': 'serverpackcreator-8.1.2-forge', 'minecraft_version': mc, 'loader_version': loader,
            'java_major': 17, 'source': batch_record, 'source_records': [batch_record, ps_record, variable_record, manifest_record] + ([original_record] if original_record else []),
            'original_scripts': [batch_record], 'jvm_args': args,
            'argument_files': [variable_record] + ([original_record] if original_record else []),
            'game_args': ['nogui'], 'java_hint': java, 'java_hint_kind': 'absolute' if Path(java).is_absolute() else 'path',
            'default_properties': {}, 'warnings': warning}


def detect(stage):
    """Read only. The caller prefers an already installed core before this."""
    stage = Path(stage)
    _checked(stage, stage, existing=False)
    stage = stage.resolve()
    roots = {stage}
    for pattern in ('startserver.bat', 'variables.txt'):
        for path in stage.rglob(pattern):
            relative = path.parent.relative_to(stage)
            if len(relative.parts) <= 4 and not any(p.casefold() in EXCLUDED for p in relative.parts):
                roots.add(path.parent)
            if len(roots) > 32:
                raise BootstrapError('初始化服务器目录过多，请选择单个服务器包。')
    found = []
    for root in sorted(roots):
        from native_server_archive import _enumerate_cores
        if _enumerate_cores(root):
            # A malformed saved selection/launch manifest is not an excuse to
            # reinstall or replace an already recognizable core.
            continue
        spec = _atm(root) or _spc(root)
        if spec:
            spec.update(server_root=root, platform='forge', restart_policy={'required_managed': True,
                'original_restart_loop': True, 'message': '原初始化脚本会循环重启或重新安装；请启用七章专属启动适配，原文件会保留。'})
            found.append(spec)
    if len(found) > 1:
        raise BootstrapError('包内存在多个初始化服务器，请分别导入，面板不会替你选择版本。')
    return found[0] if found else None


def _copy_new_files(installed, root, spec):
    """Preflight the full merge before writing; never replace an original byte."""
    original_by_case = {p.relative_to(root).as_posix().casefold(): p for p in root.rglob('*') if p.is_file()}
    plan, duplicates = [], []
    allowed_root = {'run.bat', 'run.sh', 'user_jvm_args.txt'}
    for source in installed.rglob('*'):
        if not source.is_file():
            continue
        relative = source.relative_to(installed)
        if relative.parts[0] != 'libraries' and relative.as_posix() not in allowed_root:
            continue
        _checked(installed, source)
        target = _checked(root, root / relative, existing=False)
        previous = original_by_case.get(relative.as_posix().casefold())
        if previous is not None:
            if relative.as_posix() in allowed_root:
                # Original scripts/JVM settings win even if different. The
                # generated panel profile never depends on installer run.bat.
                continue
            if _sha(previous) != _sha(source):
                raise BootstrapError('官方依赖与原包同路径文件不同，未覆盖：' + relative.as_posix())
            duplicates.append(relative.as_posix())
            continue
        if target.exists():
            raise BootstrapError('官方安装产物与原目录冲突：' + relative.as_posix())
        plan.append((source, target, relative.as_posix()))
    created, directories = [], []
    try:
        for source, target, relative in plan:
            absent = []
            parent = target.parent
            while parent != root and not parent.exists():
                absent.append(parent)
                parent = parent.parent
            for directory in reversed(absent):
                directory.mkdir()
                directories.append(directory)
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                created.append(target)
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        return {'added_files': [{'path': relative, 'sha256': _sha(target)} for _, target, relative in plan],
                'identical_original_dependencies': duplicates, '_created': created, '_directories': directories}
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        for directory in reversed(directories):
            directory.rmdir()
        raise


def prepare(stage, java_path, on_progress, cache_root=None, adapt_startup=True):
    spec = detect(stage)
    if spec is None:
        return None
    if adapt_startup is not True:
        raise BootstrapError(spec['restart_policy']['message'])
    from native_server_install import discover_java, inspect_java, resolve_versions, _download, _run_installer
    root = spec['server_root']
    candidates = [java_path] if java_path else discover_java(spec['java_major'])
    if not candidates:
        raise BootstrapError('此初始化包需要本机 64 位 Java 17，请先安装兼容 Java。')
    java = inspect_java(candidates[0], spec['java_major'])['path']
    cache = Path(cache_root) if cache_root else Path(os.environ.get('QIZHANG_CACHE_ROOT', tempfile.gettempdir())) / 'QiZhangPanel-Free-install'
    _checked(cache, cache, existing=False)
    cache = cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    installed = root.parent / ('.qizhang-bootstrap-core-' + uuid.uuid4().hex)
    installed.mkdir()
    merge = None
    try:
        on_progress(83, '识别到初始化型服务器包，正在从官方源准备 Forge ' + spec['loader_version'] + '…')
        versions = resolve_versions('forge', spec['minecraft_version'], spec['loader_version'])
        installer = _download(versions['installer_url'], cache / ('forge-' + versions['installer_version'] + '-installer.jar'),
                              versions['installer_sha1'], lambda pct, msg: on_progress(84, msg), 'Forge 官方安装器')
        log = _run_installer(java, installer, ['--installServer', str(installed)], installed, cache,
                             lambda pct, msg: on_progress(85, msg))
        expected = installed / 'libraries/net/minecraftforge/forge' / (spec['minecraft_version'] + '-' + spec['loader_version']) / 'win_args.txt'
        _checked(installed, expected)
        if not expected.read_text(encoding='utf-8-sig').strip():
            raise BootstrapError('官方安装结果缺少完整 win_args.txt。')
        # The exact requested core must be present, not an installer JAR or a
        # different fallback release. Normal archive detection verifies again.
        from native_server_archive import _enumerate_cores
        entry = expected.relative_to(installed).as_posix()
        cores = [core for core in _enumerate_cores(installed) if core[:3] == ('forge', 'args', entry)]
        if len(cores) != 1:
            raise BootstrapError('官方安装结果与初始化包指定的 Forge 版本不一致。')
        core = cores[0]
        if spec['jvm_args'] is None:
            args, record = _existing_jvm(installed)
            if args is None:
                raise BootstrapError('官方安装器未生成 JVM 参数文件，初始化未完成。')
            spec['jvm_args'] = args
            spec['argument_files'] = [record]
        # Source metadata must still be identical when installation finishes.
        for record in spec['source_records']:
            if _sha(_checked(root, root / record['path'])) != record['sha256']:
                raise BootstrapError('初始化期间原配置已变化，未绑定新的启动参数。')
        merge = _copy_new_files(installed, root, spec)
        profile = {'source': spec['source'], 'core': list(core), 'kind': 'args', 'entry': entry,
                   'java_hint': spec['java_hint'], 'java_hint_kind': spec['java_hint_kind'],
                   'jvm_args': spec['jvm_args'], 'game_args': spec['game_args'], 'classpath': [], 'main_class': '',
                   'argument_files': spec['argument_files'], 'cwd': '.', 'warnings': spec['warnings']}
        provenance = {'template': spec['template'], 'source_records': spec['source_records'],
                      'official_installer_url': versions['installer_url'], 'official_installer_sha1': versions['installer_sha1'],
                      'installer_sha256': _sha(installer), 'installer_log': str(log), 'installer_java_path': java,
                      'installer_java_major': spec['java_major'], 'game_started': False, 'original_scripts_executed': False,
                      'added_files': merge['added_files'], 'identical_original_dependencies': merge['identical_original_dependencies']}
        on_progress(86, '官方 Forge 核心已补齐；原模组、配置和启动脚本保持原样，继续生成面板启动配置…')
        return {'server_root': root, 'core': core, 'minecraft_version': spec['minecraft_version'], 'loader_version': spec['loader_version'], 'java_major': spec['java_major'],
                'java_path': java, 'profile': profile, 'original_scripts': spec['original_scripts'], 'provenance': provenance,
                'warnings': spec['warnings'], 'restart_policy': spec['restart_policy'], 'default_properties': spec['default_properties']}
    except Exception:
        if merge is not None:
            for path in reversed(merge['_created']):
                path.unlink(missing_ok=True)
            for directory in reversed(merge['_directories']):
                directory.rmdir()
        raise
    finally:
        if installed.exists() and installed.parent.resolve() == root.parent.resolve() and installed.name.startswith('.qizhang-bootstrap-core-'):
            shutil.rmtree(installed)
