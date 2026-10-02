"""Official release catalogs and server provisioning. Never launches a game server.

Copyright (c) 2026 EeryFrank — https://github.com/EeryFrank
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import threading
import time
from typing import Any, Callable
import urllib.parse
import urllib.request
import urllib.error
import uuid
import xml.etree.ElementTree as ET


class ServerInstallError(ValueError):
    pass


PLATFORMS = {"vanilla": "原版", "neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric"}
MINECRAFT_VERSION = "1.21.1"
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FORGE_METADATA = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
FORGE_PROMOTIONS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
NEOFORGE_METADATA = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
FABRIC_GAME = "https://meta.fabricmc.net/v2/versions/game"
SUPPORT_SCOPE = "正式版 Minecraft 1.12.2～1.21.11；Fabric 从 1.14 起且加载器至少 0.18.1，NeoForge 从 1.20.2 起。仅显示官方存在且有受支持 Java 要求的组合。"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ALLOWED_HOSTS = frozenset({
    "piston-meta.mojang.com", "piston-data.mojang.com", "launchermeta.mojang.com",
    "launcher.mojang.com", "maven.neoforged.net", "maven.minecraftforge.net",
    "files.minecraftforge.net", "meta.fabricmc.net", "maven.fabricmc.net",
    "fill.papermc.io", "fill-data.papermc.io", "api.purpurmc.org",
    "net-secondary.web.minecraft-services.net", "www.minecraft.net",
})
_INSTALL_LOCKS: dict[str, Any] = {}
_INSTALL_LOCKS_GUARD = threading.Lock()
_CATALOG_CACHE: dict[str, tuple[float, bytes]] = {}
_CATALOG_LOCK = threading.Lock()


def _trusted_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ServerInstallError("下载地址不属于允许的官方站点。")
    return url


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str):
    _trusted_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "QiZhangControlPanel/2.5.0 (https://github.com/EeryFrank)"})
    return urllib.request.build_opener(_OfficialRedirect()).open(request, timeout=45)


def _read(url: str, maximum: int = 16 * 1024 * 1024) -> bytes:
    with _open(url) as response:
        result = response.read(maximum + 1)
    if len(result) > maximum:
        raise ServerInstallError("官方版本资料超出允许大小。")
    return result


def _json(url: str):
    return json.loads(_read(url).decode("utf-8"))


def _check_reparse(path: Path) -> None:
    current = path.absolute()
    for candidate in (current, *current.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ServerInstallError("目录不能包含符号链接或目录联接：" + str(candidate))


def validate_server_dir(server_dir: str | Path) -> Path:
    path = Path(server_dir).expanduser()
    if not path.is_absolute():
        raise ServerInstallError("服务器目录必须使用完整绝对路径。")
    _check_reparse(path)
    path = path.resolve()
    if path == Path(path.anchor) or str(path).startswith("\\\\"):
        raise ServerInstallError("请选择本机磁盘中的专用服务器文件夹，不能使用磁盘根目录。")
    if any(c in str(path) for c in ('%', '!', '&', '^', '|', '<', '>', '\r', '\n', '"')):
        raise ServerInstallError("服务器路径不能包含百分号、感叹号、命令分隔符、换行或引号。")
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")).resolve()
    if path == windows or windows in path.parents:
        raise ServerInstallError("不能把服务器安装到 Windows 系统目录。")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ServerInstallError("请选择不存在或完全空的文件夹，已有服务器和文件不会被覆盖。")
    return path


def java_requirement(minecraft_version: str) -> dict[str, Any]:
    from native_platform_templates import minecraft_java_requirement
    return minecraft_java_requirement(minecraft_version)


def parse_java_version(output: str) -> dict[str, Any]:
    match = re.search(r'\b(?:openjdk|java)\s+(?:version\s+)?["\']?(\d+(?:[._+][0-9A-Za-z]+)*(?:-[0-9A-Za-z.]+)?)', output, re.I)
    if not match:
        raise ServerInstallError("Java 没有返回可识别的版本信息。")
    version = match.group(1)
    parts = re.split(r"[._+\-]", version)
    major = int(parts[1]) if parts[0] == "1" and len(parts) > 1 else int(parts[0])
    bits = 64 if re.search(r"64[- ]bit|\b(?:amd64|x86_64|aarch64)\b", output, re.I) else 32
    return {"major": major, "bits": bits, "version": version}


def inspect_java(java_path: str | Path, required_major: int | None = None) -> dict[str, Any]:
    if required_major is not None and (type(required_major) is not int or not 8 <= required_major <= 99):
        raise ServerInstallError("要求的 Java 主版本无效。")
    label = "64 位 Java" + (" " + str(required_major) if required_major else "（8 或更新版本）")
    if not java_path:
        raise ServerInstallError("请选择 " + label + " 的 java.exe。")
    path = Path(java_path).expanduser()
    if path.is_dir():
        path = path / "bin" / "java.exe"
    if not path.is_absolute() or not path.is_file() or path.name.lower() != "java.exe":
        raise ServerInstallError("请选择有效的 " + label + " java.exe 完整路径。")
    if any(c in str(path) for c in ('%', '!', '&', '^', '|', '<', '>', '\r', '\n', '"')):
        raise ServerInstallError("Java 路径包含启动脚本不支持的字符。")
    try:
        environment = os.environ.copy()
        for option in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
            environment.pop(option, None)
        result = subprocess.run([str(path), "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=15, check=False, env=environment)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ServerInstallError("无法验证 Java 版本，请选择可运行的 " + label + "。") from error
    output = result.stdout.decode("utf-8", errors="replace")
    info = parse_java_version(output)
    if result.returncode != 0 or info["bits"] != 64 or info["major"] < 8:
        raise ServerInstallError("请选择可运行的 " + label + "，当前程序未通过 64 位 Java 检查。")
    if required_major is not None and info["major"] != required_major:
        raise ServerInstallError("此服务器需要 " + label + "，当前选择的是 Java " + str(info["major"]) + "，请重新选择。")
    return {**info, "path": str(path.resolve())}


def validate_java(java_path: str | Path, required_major: int | None = None) -> str:
    return inspect_java(java_path, required_major)["path"]


def validate_java21(java_path: str | Path) -> str:
    """Compatibility entry point for official online 1.21.1 provisioning."""
    return validate_java(java_path, 21)


def discover_java(required_major: int | None = None) -> list[str]:
    candidates: list[Path] = []
    configured = os.environ.get("JAVA_HOME")
    if configured:
        candidates.append(Path(configured) / "bin/java.exe")
    found = shutil.which("java.exe")
    if found:
        candidates.append(Path(found))
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / name
             for name in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "BellSoft")]
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("*/bin/java.exe"))
    result, checked = [], set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in checked or not candidate.is_file():
            continue
        checked.add(key)
        try:
            resolved = validate_java(candidate, required_major)
            if resolved not in result:
                result.append(resolved)
        except ServerInstallError:
            continue
    return result


def discover_java21() -> list[str]:
    return discover_java(21)


def _number_version(value: str) -> tuple[int, ...]:
    return tuple(map(int, value.split(".")))


def _supported_minecraft(value: str) -> bool:
    return bool(isinstance(value, str) and re.fullmatch(r"1\.\d+(?:\.\d+)?", value)
                and (1, 12, 2) <= _number_version(value) <= (1, 21, 11)
                and java_requirement(value)["known"])


def _metadata_read(url: str) -> bytes:
    # Bounded in-memory caching prevents re-downloading all Maven history each
    # time the user changes a selection. No account or remote information persists.
    with _CATALOG_LOCK:
        cached = _CATALOG_CACHE.get(url)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
    raw = _read(url)
    with _CATALOG_LOCK:
        if len(_CATALOG_CACHE) >= 64:
            _CATALOG_CACHE.pop(min(_CATALOG_CACHE, key=lambda key: _CATALOG_CACHE[key][0]))
        _CATALOG_CACHE[url] = (time.monotonic(), raw)
    return raw


def _metadata_json(url: str):
    return json.loads(_metadata_read(url))


def _maven_versions(url: str) -> list[str]:
    try:
        return [node.text for node in ET.fromstring(_metadata_read(url)).findall("./versioning/versions/version") if node.text]
    except urllib.error.HTTPError as error:
        if url != NEOFORGE_METADATA or error.code != 404:
            raise
        return _metadata_json("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge")["versions"]


def _neo_game(loader: str) -> str | None:
    if not isinstance(loader, str) or not re.fullmatch(r"(?:20|21)\.\d+\.\d+", loader):
        return None
    minor, patch, _ = map(int, loader.split("."))
    mc = f"1.{minor}" + (f".{patch}" if patch else "")
    return mc if _supported_minecraft(mc) and _number_version(mc) >= (1, 20, 2) else None


def platform_versions(platform: str, minecraft_version: str | None = None) -> dict[str, Any]:
    """Official release choices; an explicit unsupported pair never silently changes."""
    if platform not in PLATFORMS:
        from native_platform_install import catalog
        return catalog(platform, minecraft_version)
    try:
        manifest = _metadata_json(MOJANG_MANIFEST)
        releases = {row["id"]: row for row in manifest["versions"]
                    if row.get("type") == "release" and _supported_minecraft(row.get("id"))}
        sources = [MOJANG_MANIFEST]
        forge, neo, promos = {}, {}, {}
        if platform == "forge":
            for artifact in _maven_versions(FORGE_METADATA):
                match = re.fullmatch(r"(1\.\d+(?:\.\d+)?)-(\d+(?:\.\d+){2,3})", artifact)
                if match and match[1] in releases:
                    forge.setdefault(match[1], []).append(match[2])
            promos = _metadata_json(FORGE_PROMOTIONS).get("promos", {})
            releases = {mc: row for mc, row in releases.items() if mc in forge}
            sources += [FORGE_METADATA, FORGE_PROMOTIONS]
        elif platform == "neoforge":
            for loader in _maven_versions(NEOFORGE_METADATA):
                mc = _neo_game(loader)
                if mc in releases:
                    neo.setdefault(mc, []).append(loader)
            releases = {mc: row for mc, row in releases.items() if mc in neo}
            sources.append(NEOFORGE_METADATA)
        elif platform == "fabric":
            games = {row.get("version") for row in _metadata_json(FABRIC_GAME) if row.get("stable") is True}
            releases = {mc: row for mc, row in releases.items() if mc in games and _number_version(mc) >= (1, 14)}
            sources.append(FABRIC_GAME)
        versions = sorted(releases, key=_number_version, reverse=True)
        if not versions:
            raise ServerInstallError("官方列表中没有当前安装器支持的正式版本。")
        mc = minecraft_version or versions[0]
        if mc not in releases:
            raise ServerInstallError(f"{PLATFORMS[platform]} 不支持所选 Minecraft {mc}，请从兼容版本列表中选择。" + SUPPORT_SCOPE)
        recommended = None
        if platform == "vanilla":
            loaders = [{"version": mc, "stable": True, "recommended": True}]
        elif platform == "forge":
            values = sorted(set(forge[mc]), key=_number_version, reverse=True)
            recommended = next((promos.get(mc + suffix) for suffix in ("-recommended", "-latest")
                                if promos.get(mc + suffix) in values), values[0])
            loaders = [{"version": value, "stable": True, "recommended": value == recommended} for value in values]
        elif platform == "neoforge":
            values = sorted(set(neo[mc]), key=_number_version, reverse=True)
            loaders = [{"version": value, "stable": True, "recommended": i == 0} for i, value in enumerate(values)]
        else:
            source = "https://meta.fabricmc.net/v2/versions/loader/" + mc
            rows = _metadata_json(source)
            values = {}
            for row in rows:
                loader = row.get("loader", {})
                value = loader.get("version", "")
                min_java = row.get("launcherMeta", {}).get("min_java_version", 8)
                # Fabric's per-game endpoint also contains ancient loaders.
                # Bound selectable releases to the generation recommended for
                # our newest supported MC (fabricmc.net/2025/12/05/12111.html).
                if (re.fullmatch(r"\d+\.\d+\.\d+", value) and _number_version(value) >= (0, 18, 1) and type(min_java) is int
                        and min_java <= java_requirement(mc)["major"]
                        and row.get("intermediary", {}).get("version", mc) == mc):
                    values[value] = loader.get("stable") is True
            stable = [value for value in values if values[value]]
            if not stable:
                raise ServerInstallError("官方列表中没有可使用所需 Java 版本运行的 Fabric 正式加载器。")
            recommended = max(stable, key=_number_version)
            loaders = [{"version": value, "stable": values[value], "recommended": value == recommended}
                       for value in sorted(values, key=_number_version, reverse=True)]
            sources.append(source)
        return {"platform": platform, "minecraft_versions": versions, "default_minecraft_version": versions[0],
                "minecraft_version": mc, "loader_versions": loaders,
                "default_loader_version": next(row["version"] for row in loaders if row["recommended"]),
                "java_requirement": java_requirement(mc), "sources": sources, "support_scope": SUPPORT_SCOPE}
    except ServerInstallError:
        raise
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        raise ServerInstallError("无法读取官方版本列表，请检查网络后重试：" + str(error)) from error


def resolve_versions(platform: str, minecraft_version: str = MINECRAFT_VERSION,
                     loader_version: str | None = None) -> dict[str, Any]:
    catalog = platform_versions(platform, minecraft_version)
    loader = loader_version or catalog["default_loader_version"]
    if loader not in {row["version"] for row in catalog["loader_versions"]}:
        raise ServerInstallError("所选加载器版本不属于该 Minecraft 的官方兼容列表，请重新选择。")
    result: dict[str, Any] = {"platform": platform, "minecraft_version": minecraft_version,
                              "loader_version": loader, "java_requirement": catalog["java_requirement"]}
    manifest = _metadata_json(MOJANG_MANIFEST)
    match = next(v for v in manifest["versions"] if v["id"] == minecraft_version and v["type"] == "release")
    _trusted_url(match["url"])
    version_raw = _read(match["url"])
    if hashlib.sha1(version_raw).hexdigest() != match["sha1"]:
        raise ServerInstallError("Minecraft 版本资料校验失败。")
    version = json.loads(version_raw)
    official_java = version.get("javaVersion", {}).get("majorVersion")
    if official_java is not None and official_java != result["java_requirement"]["major"]:
        raise ServerInstallError("官方 Java 要求与当前受支持规则不同，暂不安装该版本；请更新面板。")
    if not version.get("downloads", {}).get("server"):
        raise ServerInstallError("这个官方版本没有可下载的独立服务端。")
    server = version["downloads"]["server"]
    _trusted_url(server["url"])
    result.update({"minecraft_server": server, "minecraft_manifest": match["url"], "minecraft_manifest_sha1": match["sha1"]})
    if platform == "vanilla":
        return result
    if platform == "neoforge":
        installer = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{loader}/neoforge-{loader}-installer.jar"
        result.update({"loader_version": loader, "installer_version": loader, "installer_url": installer})
    elif platform == "forge":
        artifact = minecraft_version + "-" + loader
        installer = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{artifact}/forge-{artifact}-installer.jar"
        result.update({"loader_version": loader, "installer_version": artifact, "installer_url": installer})
    else:
        installers = _metadata_json("https://meta.fabricmc.net/v2/versions/installer")
        installer = next((row for row in installers if row.get("stable")), None)
        if not installer or not re.fullmatch(r"\d+\.\d+\.\d+", installer["version"]):
            raise ServerInstallError("官方列表中没有兼容的 Fabric 正式版本。")
        expected_url = f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/{installer['version']}/fabric-installer-{installer['version']}.jar"
        if installer["url"] != expected_url:
            raise ServerInstallError("Fabric 安装器地址与官方 Maven 路径不一致。")
        result.update({"loader_version": loader, "installer_version": installer["version"], "installer_url": expected_url})
    checksum = _read(result["installer_url"] + ".sha1", 4096).decode("ascii").strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{40}", checksum):
        raise ServerInstallError("官方安装器校验信息无效。")
    result["installer_sha1"] = checksum
    return result


def _digest(path: Path, algorithm: str = "sha1") -> str:
    checksum = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _download(url: str, destination: Path, expected_sha1: str, progress: Callable[[int, str], None], label: str) -> Path:
    _trusted_url(url)
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha1):
        raise ServerInstallError("下载文件缺少有效的官方校验值。")
    _check_reparse(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _digest(destination) == expected_sha1:
        progress(25, "使用已校验的下载缓存：" + label)
        return destination
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
    try:
        with _open(url) as response, temporary.open("xb") as output:
            total = int(response.headers.get("Content-Length", "0") or 0)
            received, updated = 0, 0.0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > 512 * 1024 * 1024:
                    raise ServerInstallError("下载文件超过允许大小。")
                output.write(chunk)
                if time.monotonic() - updated >= .5:
                    progress(15 + min(20, int(20 * received / total)) if total else 20, "正在下载" + label + f"（{received // (1024 * 1024)} MB）")
                    updated = time.monotonic()
            output.flush()
            os.fsync(output.fileno())
        if _digest(temporary) != expected_sha1:
            raise ServerInstallError("下载校验失败，请重试：" + label)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _run_installer(java: str, installer: Path, arguments: list[str], stage: Path,
                   cache: Path, progress: Callable[[int, str], None]) -> Path:
    logs = cache / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / (stage.name + ".log")
    temporary = cache / "java-tmp" / stage.name
    temporary.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["JAVA_HOME"] = str(Path(java).parent.parent)
    environment["PATH"] = str(Path(java).parent) + os.pathsep + environment.get("PATH", "")
    for option in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        environment.pop(option, None)
    command = [java, "-Xmx2G", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
               "-Djava.io.tmpdir=" + str(temporary), "-jar", str(installer), *arguments]
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=stage, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        started = time.monotonic()
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > 1200:
                    raise ServerInstallError("官方安装器运行超时，日志：" + str(log))
                progress(min(85, 40 + int(elapsed / 15)), "官方安装器正在准备服务端依赖，请等待…")
                time.sleep(1)
            if process.returncode != 0:
                raise ServerInstallError("官方安装器未能完成，退出码 " + str(process.returncode) + "。日志：" + str(log))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    return log


def _free_port(start: int, excluded: set[int] | None = None) -> int:
    for port in range(start, min(65535, start + 1000)):
        if excluded and port in excluded:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise ServerInstallError("没有可用的服务器端口，请先检查端口占用。")


def _seed_launchers(stage: Path, java: str, versions: dict[str, Any], eula_accepted: bool) -> None:
    platform = versions["platform"]
    server_id = versions.setdefault("server_id", "server-" + uuid.uuid4().hex[:12])
    java_major = java_requirement(versions["minecraft_version"])["major"]
    marker = "-Dqizhang.panel.server_id=" + server_id
    java_command = '"%QZ_JAVA%" ' + marker
    header = ('@echo off\nchcp 65001 >nul\nsetlocal DisableDelayedExpansion\ncd /d "%~dp0"\n'
              'set "QZ_JAVA="\nif exist "%~dp0qizhang-java-path.txt" set /p QZ_JAVA=<"%~dp0qizhang-java-path.txt"\n'
              'if not exist "%QZ_JAVA%" (\n echo Selected Java is missing. Choose a compatible Java in server settings. 1>&2\n exit /b 12\n)\n')
    legacy_forge = platform == "forge" and java_major == 8
    if legacy_forge:
        from native_server_archive import jar_manifest, LEGACY_FORGE_MAINS
        artifact = versions["installer_version"]
        candidates = [stage / f"forge-{artifact}{suffix}.jar" for suffix in ("", "-universal")]
        cores = [path for path in candidates if path.is_file() and jar_manifest(path).get("Main-Class") in LEGACY_FORGE_MAINS]
        if len(cores) != 1 or not any((stage / "libraries").rglob("*.jar")):
            raise ServerInstallError("旧版 Forge 安装结果缺少唯一可启动核心或 libraries 依赖，安装未完成。")
        payload = cores[0].name
    elif platform in {"neoforge", "forge"}:
        run = stage / "run.bat"
        if not run.is_file():
            raise ServerInstallError("官方安装器没有生成 run.bat，安装未完成。")
        text = run.read_text(encoding="utf-8-sig")
        arguments = stage / "libraries" / ("net/neoforged/neoforge" if platform == "neoforge" else "net/minecraftforge/forge") / (versions["loader_version"] if platform == "neoforge" else versions["installer_version"]) / "win_args.txt"
        if not arguments.is_file() or arguments.stat().st_size == 0:
            raise ServerInstallError("官方安装器没有生成完整的 Windows 启动参数。")
        expected_argument = arguments.relative_to(stage).as_posix()
        java_lines = re.findall(r"(?mi)^[ \t]*java(?:\.exe)?[ \t]+([^\r\n]+)", text)
        argument_pattern = r'(?<!\S)@(?:"' + re.escape(expected_argument) + r'"|' + re.escape(expected_argument) + r')(?=\s|$)'
        memory_pattern = r'(?<!\S)@(?:"user_jvm_args\.txt"|user_jvm_args\.txt)(?=\s|$)'
        launch_lines = [line for line in java_lines if re.search(argument_pattern, line.replace("\\", "/"), re.I)
                        and re.search(memory_pattern, line, re.I)]
        if len(launch_lines) != 1:
            raise ServerInstallError("官方启动脚本缺少唯一、完整的服务端启动命令，安装未完成。")
        text, count = re.subn(r"(?mi)^([ \t]*)java(?:\.exe)?(?=[ \t])", lambda m: m.group(1) + java_command, text)
        if count < 1:
            raise ServerInstallError("无法识别官方启动脚本中的 Java 命令，已保留现有目录不变。")
        text = re.sub(r"(?mi)^[ \t]*pause[ \t]*$", "", text)
        run.write_text(header + text, encoding="utf-8", newline="\r\n")
    else:
        jar = "server.jar" if platform == "vanilla" else "fabric-server-launch.jar"
        if not (stage / jar).is_file():
            raise ServerInstallError("安装结果缺少服务端启动文件：" + jar)
        payload = jar
        if java_major != 8:
            (stage / "run.bat").write_text(header + java_command + ' @user_jvm_args.txt -jar "' + jar + '" %*\nexit /b %errorlevel%\n', encoding="utf-8", newline="\r\n")
    if java_major == 8:
        from native_server_archive import _write_java8_launcher
        launcher = _write_java8_launcher(stage, payload, server_id)
        (stage / "run.bat").write_text('@echo off\r\nsetlocal DisableDelayedExpansion\r\ncall "%~dp0' + launcher + '" %*\r\nexit /b %errorlevel%\r\n', encoding="utf-8")
        versions["launch_script"] = launcher
    else:
        versions["launch_script"] = "start-server.bat"
    (stage / "start-server.bat").write_text('@echo off\nrem ' + marker + '\nchcp 65001 >nul\nsetlocal DisableDelayedExpansion\ncd /d "%~dp0"\ncall "%~dp0run.bat" ' + ("" if java_major == 8 else "nogui ") + '%*\nexit /b %errorlevel%\n', encoding="utf-8", newline="\r\n")
    (stage / "qizhang-java-path.txt").write_text(java + "\n", encoding="utf-8")
    (stage / "user_jvm_args.txt").write_text("-Xms2G\n-Xmx4G\n-Dfile.encoding=UTF-8\n", encoding="utf-8", newline="\r\n")
    game_port = _free_port(25565)
    rcon_port = _free_port(25575, {game_port})
    properties = (f"server-port={game_port}\nserver-ip=\nonline-mode=true\nmax-players=20\n"
                  "motd=QiZhang Minecraft Server\nview-distance=8\nsimulation-distance=6\n"
                  "enable-command-block=false\nwhite-list=false\nspawn-protection=16\n"
                  f"enable-rcon=true\nrcon.port={rcon_port}\nrcon.password={secrets.token_urlsafe(24)}\n"
                  "broadcast-rcon-to-ops=false\n")
    (stage / "server.properties").write_text(properties, encoding="utf-8", newline="\r\n")
    (stage / "eula.txt").write_text("# https://www.minecraft.net/eula\neula=" + str(eula_accepted).lower() + "\n", encoding="utf-8")
    if platform != "vanilla":
        (stage / "mods").mkdir(exist_ok=True)


def _delete_stage(stage: Path, parent: Path) -> None:
    _check_reparse(stage)
    if stage.parent.resolve() != parent.resolve() or not stage.name.startswith(".qizhang-server-install-"):
        raise ServerInstallError("安装临时目录验证失败，已保留文件。")
    if stage.exists():
        for root, directories, files in os.walk(stage, followlinks=False):
            for name in directories + files:
                _check_reparse(Path(root) / name)
        shutil.rmtree(stage)


def install_server(platform: str, server_dir: str | Path, java_path: str | Path,
                   on_progress: Callable[[int, str], None] | None = None, eula_accepted: bool = False,
                   minecraft_version: str = MINECRAFT_VERSION, cache_root: str | Path | None = None,
                   loader_version: str | None = None) -> dict[str, Any]:
    if platform not in PLATFORMS:
        from native_platform_install import install
        return install(platform, server_dir, java_path, on_progress or (lambda *_: None), minecraft_version=minecraft_version,
                       loader_version=loader_version, cache_root=cache_root, eula_accepted=eula_accepted)
    if not _supported_minecraft(minecraft_version):
        raise ServerInstallError("请选择支持的 Minecraft 服务器类型和正式版本。" + SUPPORT_SCOPE)
    if not isinstance(eula_accepted, bool):
        raise ServerInstallError("EULA 同意状态必须为明确的布尔值。")
    target = validate_server_dir(server_dir)
    required_java = java_requirement(minecraft_version)["major"]
    candidates = discover_java(required_java) if not java_path else [java_path]
    if not candidates:
        raise ServerInstallError(f"未检测到兼容的 64 位 Java {required_java}，请安装后重新选择。")
    java = validate_java(candidates[0], required_java)
    progress = on_progress or (lambda _percent, _message: None)
    cache = Path(cache_root) if cache_root else Path(os.environ.get('QIZHANG_CACHE_ROOT', tempfile.gettempdir())) / 'QiZhangPanel-Free-install'
    if not cache.is_absolute():
        raise ServerInstallError("下载缓存必须使用绝对路径。")
    _check_reparse(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with _INSTALL_LOCKS_GUARD:
        lock = _INSTALL_LOCKS.setdefault(os.path.normcase(str(target)), threading.Lock())
    if not lock.acquire(blocking=False):
        raise ServerInstallError("这个目录正在安装服务器，请等待完成。")
    stage = target.parent / (".qizhang-server-install-" + uuid.uuid4().hex)
    was_empty_directory = target.is_dir()
    try:
        validate_server_dir(target)
        progress(3, f"正在核对官方版本与 Java {required_java}…")
        versions = resolve_versions(platform, minecraft_version, loader_version)
        _check_reparse(target.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.mkdir()
        if platform == "vanilla":
            server = versions["minecraft_server"]
            downloaded = _download(server["url"], cache / ("minecraft-server-" + minecraft_version + ".jar"), server["sha1"], progress, "原版服务端")
            shutil.copy2(downloaded, stage / "server.jar")
            versions["server_sha256"] = _digest(downloaded, "sha256")
        else:
            filename = platform + "-" + versions["installer_version"] + "-installer.jar"
            installer = _download(versions["installer_url"], cache / filename, versions["installer_sha1"], progress, PLATFORMS[platform] + " 安装器")
            versions["installer_sha256"] = _digest(installer, "sha256")
            # Old Forge installers install into cwd; no modern target argument
            # or Java @argument-file semantics are assumed for Java 8 servers.
            arguments = (["--installServer"] if platform == "forge" and required_java == 8 else ["--installServer", str(stage)]) if platform in {"neoforge", "forge"} else ["server", "-mcversion", minecraft_version, "-loader", versions["loader_version"], "-downloadMinecraft", "-dir", str(stage)]
            log = _run_installer(java, installer, arguments, stage, cache, progress)
            versions["installer_log"] = str(log)
        progress(90, "正在检查服务端文件并生成启动配置…")
        _seed_launchers(stage, java, versions, eula_accepted)
        from native_platform_templates import receipt as template_receipt
        receipt = {**versions, "platform_template": template_receipt(platform), "installed_at": datetime.now(timezone.utc).isoformat(), "java_path": java,
                   "eula_accepted": eula_accepted, "game_started": False,
                   "sources": [versions["minecraft_manifest"], versions.get("installer_url", versions["minecraft_server"]["url"])]}
        (stage / "qizhang-install-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        validate_server_dir(target)
        _check_reparse(stage)
        if target.exists():
            target.rmdir()  # Rechecked empty immediately above; never removes existing content.
        try:
            stage.rename(target)
        except Exception:
            if was_empty_directory and not target.exists():
                target.mkdir()
            raise
        definition = {"id": versions["server_id"], "name": PLATFORMS[platform] + " " + minecraft_version,
                      "path": str(target), "platform": platform, "platform_template": template_receipt(platform), "minecraft_version": minecraft_version,
                      "loader_version": versions["loader_version"], "content_version": "官方基础服务端",
                      "launch_script": versions["launch_script"], "control_script": None, "supports_watchdog": False,
                      "voice_port": 24454, "java_major": required_java,
                      "java_selection": {"source": "local-manual" if java_path else "local-auto",
                                         "selected_major": required_java, "selected_path": java,
                                         "message": ("已使用指定的" if java_path else "已自动选择本机的") + f" 64 位 Java {required_java}。"}}
        progress(100, "服务器已安装，尚未启动。" + ("" if eula_accepted else "首次开服前需要同意 Minecraft EULA。"))
        return definition
    finally:
        try:
            if stage.exists():
                _delete_stage(stage, target.parent)
        finally:
            lock.release()
