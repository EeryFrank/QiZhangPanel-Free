# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Editable, version-checked startup settings without rewriting original scripts."""
from pathlib import Path
import json
import os
import re
import uuid

from server_manager import PanelError, atomic_write_json, atomic_write_text
from native_server_archive import detect_core, detect_minecraft_version, _legacy_catserver_profile, CATSERVER_MAIN, jar_manifest
from native_server_install import java_requirement, inspect_java

CONFIG = "qizhang-startup.json"
LAUNCHER = "qizhang-managed-start.bat"
SCRIPT = "qizhang-managed-start.ps1"
IMPORT_JVM_FILE = "qizhang-startup.jvm-args.txt"


def jvm_filename(config):
    name = config.get("jvm_file", "user_jvm_args.txt")
    if name not in {"user_jvm_args.txt", IMPORT_JVM_FILE}:
        raise PanelError("面板 JVM 参数文件名无效，原启动文件未修改。")
    return name


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise PanelError("启动配置路径不能包含符号链接或目录联接，原文件未修改。")


def _target(root, name):
    path = root / name
    _no_links(path)
    if not path.resolve().is_relative_to(root.resolve()) or (path.exists() and not path.is_file()):
        raise PanelError("启动配置目标不是服务器目录中的普通文件。")
    return path


def _read_json(path):
    _no_links(path)
    if path.stat().st_size > 128 * 1024:
        raise PanelError("启动配置文件过大，请检查原文件。")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise PanelError("启动配置格式无效。")
    return value


def _relative(root, name):
    path = root / str(name)
    if Path(str(name)).is_absolute() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise PanelError("启动文件不在当前服务器目录内，或已不存在。")
    for part in [path, *path.parents]:
        if part == root.parent:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise PanelError("启动文件不能通过目录联接或链接指向其他位置。")
    return path.relative_to(root).as_posix()


def _lines(value, label):
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not isinstance(value, list) or len(value) > 128:
        raise PanelError(label + "请每行填写一个参数，最多 128 项。")
    if any(not isinstance(arg, str) or not arg or len(arg) > 4096 or any(ord(c) < 32 for c in arg) for arg in value):
        raise PanelError(label + "包含无效参数或控制字符。")
    return list(value)


def _jvm_file(root, name="user_jvm_args.txt"):
    file = _target(root, jvm_filename({"jvm_file": name}))
    if not file.is_file():
        return ["-Xms2G", "-Xmx4G"]
    # Existing Java argument files allow several flags per line. Quoted values
    # remain one argument; editing UI subsequently uses one argument per line.
    if file.stat().st_size > 128 * 1024:
        raise PanelError("JVM 参数文件过大，请检查原文件。")
    text = file.read_text(encoding="utf-8-sig")
    result = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        for token in re.findall(r'(?:[^\s"]+|"[^"]*")+', line):
            result.append(token.replace('"', ''))
    return result


def inspect(manager, definition=None):
    from native_platforms import profile
    spec = profile(getattr(manager, 'platform', 'vanilla'), manager.server_root)
    if spec['runtime'] in {'native', 'php'}:
        from native_platform_launch import inspect as inspect_platform
        return inspect_platform(manager)
    root = manager.server_root
    reason = ""
    try:
        core = detect_core(root)
        if core is None:
            raise PanelError("未识别到唯一服务端核心；保留原启动脚本，暂不能自动改写启动参数。")
        mc, evidence = detect_minecraft_version(root, core)
        mc = mc or str((definition or {}).get("minecraft_version", ""))
        cfg = {"schema": 1, "server_id": manager.server_id, "minecraft_version": mc,
               "platform": core[0], "kind": core[1], "entry": core[2], "classpath": [],
               "main_class": "", "server_args": ["nogui"] if spec['family'] == 'java' else []}
        if (root / CONFIG).is_file():
            old = _read_json(root / CONFIG)
            cfg["jvm_file"] = jvm_filename(old)
            for key in ("kind", "entry", "classpath", "main_class", "server_args"):
                if key in old:
                    cfg[key] = old[key]
            cfg["jvm_args"] = _jvm_file(root, cfg["jvm_file"])
        else:
            manifest = root / "qizhang-import-launch.json"
            launch = _read_json(manifest) if manifest.is_file() else {}
            if core[1] == "jar" and jar_manifest(root / core[2]).get("Main-Class") == CATSERVER_MAIN and not launch.get("classpath"):
                launch = _legacy_catserver_profile(root, core)
            jvm = _jvm_file(root)
            if launch.get("classpath"):
                cfg.update(kind="classpath", classpath=launch["classpath"], main_class=launch["main_class"], server_args=launch.get("game_args", ["nogui"]))
                jvm = [arg for arg in launch.get("jvm_args", []) if not re.match(r"^-Xm[sx]", arg)] + jvm
            elif core[1] == "jar" and launch.get("core_jar") == core[2] and "game_args" in launch:
                cfg["server_args"] = _lines(launch["game_args"], "服务端参数")
            cfg["jvm_args"] = jvm
        cfg["entry"] = _relative(root, cfg["entry"])
        if cfg["entry"] != core[2]:
            raise PanelError("保存的启动入口与当前唯一核心不一致，请先检查原配置。")
        cfg["classpath"] = [_relative(root, part) for part in cfg["classpath"]]
        if cfg["kind"] == "classpath" and (not cfg["classpath"] or not re.fullmatch(r"[A-Za-z_$][\w.$]*", cfg["main_class"])):
            raise PanelError("启动主类或 classpath 无效，请检查原始启动配置。")
        if cfg["kind"] == "classpath" and (core[1] != "jar" or cfg["entry"] not in cfg["classpath"] or
                cfg["main_class"] != jar_manifest(root / core[2]).get("Main-Class")):
            raise PanelError("Classpath 或启动主类与当前唯一核心不匹配。")
        if cfg["kind"] != "classpath" and cfg["kind"] != core[1]:
            raise PanelError("保存的启动类型与当前核心格式不一致。")
        if cfg["kind"] not in {"jar", "args", "classpath"}:
            raise PanelError("暂不支持这种启动入口，原文件已保留。")
        selected = _target(root, "qizhang-java-path.txt")
        java = selected.read_text(encoding="utf-8-sig").strip() if selected.is_file() else str(manager.java_path)
        cfg["java_path"] = java
        from native_server_archive import core_java_requirement
        requirement = core_java_requirement(root, core, mc)
        if spec['family'] == 'proxy' or spec['id'] == 'nukkit':
            # A class format is a minimum, not a demand to downgrade a newer
            # explicitly selected runtime (dependencies may require newer Java).
            requirement = dict(requirement, minimum_major=requirement['major'], major=None)
        if cfg["kind"] == "args" and requirement["major"] == 8:
            raise PanelError("Java 8 不支持 @参数文件启动，请保留兼容的旧版 JAR/ClassPath 启动方式。")
        cfg.update(supported=True, java_requirement=requirement, version_evidence=evidence,
                   platform_profile=spec, runtime='java', java_applicable=True,
                   launch_script=manager.launch_script, message="每行一个参数。保存仅在完全停服时允许，下一次开服生效；原启动脚本保留。")
        return cfg
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        reason = str(error)
    return {"supported": False, "launch_script": manager.launch_script, "message": reason}


def _validate_jvm(args, java_major):
    heaps = {}
    prefixes = ("-X", "-XX:", "-D", "-javaagent:", "-agentlib:", "-agentpath:", "-verbose", "-ea", "-da",
                "--add-opens=", "--add-exports=", "--add-modules=", "--enable-native-access=")
    for arg in args:
        if '"' in arg:
            raise PanelError("JVM 参数每行直接填写值，不要嵌入双引号；空格会由面板自动处理。")
        if not arg.startswith(prefixes) or arg.startswith("-Dqizhang.panel.server_id"):
            raise PanelError("JVM 参数不支持该选项，或正在覆盖面板实例标识：" + arg[:100])
        if arg.startswith("--") and java_major < 9:
            raise PanelError("Java 8 不支持 --add-opens 等模块参数，请移除后再保存。")
        if arg.startswith(("-Xms", "-Xmx")):
            match = re.fullmatch(r"-Xm([sx])(\d+)([mMgG])", arg)
            if not match:
                raise PanelError("内存参数格式应为 -Xms1G / -Xmx4G，请每行只填一个参数。")
            key, amount, unit = match.groups()
            if key in heaps:
                raise PanelError("最小、最大内存参数分别只能出现一次。")
            heaps[key] = int(amount) * (1024 if unit.lower() == "g" else 1)
            if heaps[key] < 64:
                raise PanelError("Java 堆内存不能少于 64 MB。")
    if "s" in heaps and "x" in heaps and heaps["s"] > heaps["x"]:
        raise PanelError("最小内存不能大于最大内存。")


PS_SCRIPT = r'''$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'qizhang-startup.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$java = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'qizhang-java-path.txt') -Raw -Encoding UTF8).Trim()
if (-not [System.IO.Path]::IsPathRooted($java)) { $java = Join-Path $PSScriptRoot $java }
if (-not (Test-Path -LiteralPath $java -PathType Leaf)) { throw 'Selected Java is missing. Choose a compatible runtime in startup settings.' }
$jvm = @()
foreach ($line in (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'user_jvm_args.txt') -Encoding UTF8)) {
    $line = $line.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    foreach ($token in [regex]::Matches($line, '(?:[^\s"]+|"[^"]*")+')) { $jvm += $token.Value.Replace('"', '') }
}
$javaArgs = @($jvm) + @(('-Dqizhang.panel.server_id=' + $cfg.server_id))
if ($cfg.kind -eq 'args') { $javaArgs += @('@' + $cfg.entry) }
elseif ($cfg.kind -eq 'classpath') { $javaArgs += @('-cp', ($cfg.classpath -join ';'), $cfg.main_class) }
elseif ($cfg.kind -eq 'jar') { $javaArgs += @('-jar', $cfg.entry) }
else { throw 'Unsupported entry point.' }
$javaArgs += @($cfg.server_args) + @($args)
# Quote once for Windows native argv; PowerShell 5's legacy native binder loses
# embedded quotes. Relay both byte streams to panel log capture below.
function Quote-QizhangArgument([string]$value) {
    if ($value.Length -gt 0 -and $value -notmatch '[\s"]') { return $value }
    $value = [regex]::Replace($value, '(\\*)"', '$1$1\"')
    $value = [regex]::Replace($value, '(\\+)$', '$1$1')
    return '"' + $value + '"'
}
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $java
$start.Arguments = (@($javaArgs | ForEach-Object { Quote-QizhangArgument ([string]$_) }) -join ' ')
$start.WorkingDirectory = $PSScriptRoot
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.RedirectStandardInput = $true
foreach ($name in @('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')) { $start.EnvironmentVariables.Remove($name) }
$process = [System.Diagnostics.Process]::Start($start)
try {
    $process.StandardInput.Close()
    # Copy both pipes concurrently as raw bytes: no PS event runspace, encoding
    # conversion or buffered ReadToEnd that can hide output while MC is starting.
    $outCopy = $process.StandardOutput.BaseStream.CopyToAsync([Console]::OpenStandardOutput())
    $errCopy = $process.StandardError.BaseStream.CopyToAsync([Console]::OpenStandardError())
    $process.WaitForExit()
    $outCopy.Wait(); $errCopy.Wait()
    $code = $process.ExitCode
} finally { $process.Dispose() }
exit $code
'''


def managed_script(config):
    return PS_SCRIPT.replace("'user_jvm_args.txt'", "'" + jvm_filename(config) + "'")


def write_imported_launch(root, config, jvm_args):
    """Write into the importer's private staging directory; never run archive code."""
    config = dict(config, schema=1, jvm_file=IMPORT_JVM_FILE)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", str(config.get("server_id", ""))):
        raise PanelError("服务器实例标识无效。")
    _relative(root, config["entry"])
    for name in config.get("classpath", []):
        _relative(root, name)
    jvm = _lines(jvm_args, "原启动文件 JVM 参数")
    _validate_jvm(jvm, config["java_major"])
    game = _lines(config["server_args"], "原启动文件服务端参数")
    for arg in game:
        if arg.startswith("@") or re.match(r"^(?:--(?:port|host|ip|server-ip|server-port)(?:=|\s|$)|-p)", arg, re.I):
            raise PanelError("原启动参数覆盖了监听地址、端口或引用额外参数文件；请取消启动适配沿用原入口，或先将这些设置移到 server.properties。")
    config["server_args"] = game
    script = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
              f'rem -Dqizhang.panel.server_id={config["server_id"]}\r\n'
              'cd /d "%~dp0"\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qizhang-managed-start.ps1" %*\r\nexit /b %errorlevel%\r\n')
    atomic_write_json(_target(root, CONFIG), config)
    atomic_write_text(_target(root, SCRIPT), managed_script(config), "utf-8-sig")
    atomic_write_text(_target(root, LAUNCHER), script, "utf-8")
    atomic_write_text(_target(root, IMPORT_JVM_FILE), "\n".join('"' + arg + '"' if " " in arg else arg for arg in jvm) + "\n", "utf-8")
    return LAUNCHER


def save(manager, payload, definition=None, persist_launcher=None):
    if not isinstance(payload, dict):
        raise PanelError("启动设置格式无效。")
    from native_platforms import profile
    if profile(getattr(manager, 'platform', 'vanilla'))['runtime'] in {'native', 'php'}:
        from native_platform_launch import save as save_platform
        return save_platform(manager, payload, persist_launcher)
    # Host also holds run_direct_mutation. Keep the same reservation lock order
    # through validation and all writes, so start/stop cannot race configuration.
    with manager._shutdown_countdown_lock, manager._operation_lock:
        reason = manager._server_endpoint_lock_reason(force=True)
        if reason:
            raise PanelError(reason)
        current = inspect(manager, definition)
        if not current.get("supported"):
            raise PanelError(current["message"])
        java_value = str(payload.get("java_path", current["java_path"])).strip()
        java = Path(java_value)
        if not java.is_absolute():
            java = manager.server_root / java
        info = inspect_java(java, current["java_requirement"]["major"])
        minimum = current['java_requirement'].get('minimum_major')
        if minimum and info['major'] < minimum:
            raise PanelError('该入口至少需要 Java ' + str(minimum) + '。')
        if current["kind"] == "args" and info["major"] < 9:
            raise PanelError("Java 8 不支持 @参数文件启动，请选择兼容的 Java 或旧版 JAR/ClassPath 启动方式。")
        jvm = _lines(payload.get("jvm_args", current["jvm_args"]), "JVM 参数")
        game = _lines(payload.get("server_args", current["server_args"]), "服务端参数")
        _validate_jvm(jvm, info["major"])
        for arg in game:
            if arg.startswith("@"):
                raise PanelError("服务端参数不允许再引用 @参数文件，请逐行填写明确的游戏参数。")
            if re.match(r"^(?:--(?:port|host|ip|server-ip|server-port)(?:=|\s|$)|-p)", arg, re.I):
                raise PanelError("监听地址和游戏端口请在游戏设置中修改，不能用启动参数覆盖。")
        root = manager.server_root
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", str(manager.server_id)):
            raise PanelError("服务器实例标识无效，请重新选择服务器。")
        resolved = Path(info["path"])
        java_saved = resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else str(resolved)
        config = {key: current[key] for key in ("schema", "server_id", "minecraft_version", "platform", "kind", "entry", "classpath", "main_class")}
        config.update(java_major=info["major"], java_path=java_saved, server_args=game)
        config["jvm_file"] = jvm_filename(current)
        files = [CONFIG, SCRIPT, LAUNCHER, "qizhang-java-path.txt", config["jvm_file"]]
        targets = {name: _target(root, name) for name in files}
        backup = manager.data_root / "startup-backups" / uuid.uuid4().hex
        _no_links(backup)
        backup.mkdir(parents=True)
        old = {name: targets[name].read_bytes() if targets[name].is_file() else None for name in files}
        for name, content in old.items():
            if content is not None:
                (backup / name).write_bytes(content)
        try:
            atomic_write_json(root / CONFIG, config)
            atomic_write_text(root / SCRIPT, managed_script(config), "utf-8-sig")
            script = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                      f'rem -Dqizhang.panel.server_id={manager.server_id}\r\n'
                      'cd /d "%~dp0"\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qizhang-managed-start.ps1" %*\r\nexit /b %errorlevel%\r\n')
            atomic_write_text(root / LAUNCHER, script, "utf-8")
            atomic_write_text(root / "qizhang-java-path.txt", java_saved + "\n", "utf-8")
            # Java argument files accept quotes around values with spaces.
            atomic_write_text(root / config["jvm_file"], "\n".join('"' + arg + '"' if " " in arg else arg for arg in jvm) + "\n", "utf-8")
            if persist_launcher is not None:
                persist_launcher(LAUNCHER)
        except Exception as error:
            failed = []
            for name, content in old.items():
                try:
                    target = _target(root, name)
                    if content is None:
                        target.unlink(missing_ok=True)
                    else:
                        temporary = root / (".qizhang-restore-" + uuid.uuid4().hex + ".tmp")
                        try:
                            temporary.write_bytes(content)
                            os.replace(temporary, target)
                        finally:
                            temporary.unlink(missing_ok=True)
                except (OSError, PanelError):
                    failed.append(name)
            if failed:
                raise PanelError("启动配置保存失败，部分文件无法自动恢复。原文件备份位于：" + str(backup)) from error
            raise
        manager.java_path = resolved
        manager.launch_script = LAUNCHER
        manager.jvm_args_path = root / config["jvm_file"]
        return {"launch_script": LAUNCHER, "message": "启动配置已保存，下一次开服生效。原启动脚本已保留。", "backup_directory": str(backup), "java_major": info["major"]}
