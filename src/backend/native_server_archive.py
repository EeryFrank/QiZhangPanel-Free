# 七章控制面板项目归属：EeryFrank。项目主页：https://github.com/EeryFrank
"""Install a user-supplied server ZIP without executing anything from the archive."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from urllib.parse import unquote, urlsplit
import uuid
import zipfile

MAX_EXPANDED = 40 * 1024**3
MAX_FILES = 150_000
MAX_JAVA_DEPTH = 8
MAX_JAVA_DIRECTORIES = 4096
MAX_JAVA_REPORT_ITEMS = 128
LAUNCH_MANIFEST = "qizhang-server-launch.json"
from native_platform_templates import (CATSERVER_MAIN, CATSERVER_STANDARD_MAIN, LEGACY_FORGE_MAINS,
                                       VANILLA_MAINS, BUKKIT_MAINS, JAVA_SERVER_MAINS, PAPERCLIP_MAIN)



class ArchiveInstallError(ValueError):
    pass


class ArchiveSelectionRequired(ArchiveInstallError):
    """A fresh, verified list of possible entry points for an explicit choice."""
    def __init__(self, choices, message="压缩包内存在多个可用的服务端启动目标，请选择要导入的一项；无需删除原文件。"):
        super().__init__(message)
        self.choices = choices


def check_uninstalled_modpack(package):
    """Recognize index-only modpacks without conflating them with server ZIPs.

    Existing real server entries take precedence: re-exported installed servers
    sometimes retain their original modpack index.
    """
    entries = package.infolist()
    indexes = [i for i in entries if PurePosixPath(i.filename.replace('\\', '/')).name == 'modrinth.index.json'
               and len(PurePosixPath(i.filename.replace('\\', '/')).parts) <= 4]
    if len(indexes) != 1:
        return
    index = indexes[0]
    if index.file_size > 8 * 1024**2:
        raise ArchiveInstallError('Modrinth 整合包清单超过允许大小。')
    prefix = PurePosixPath(index.filename.replace('\\', '/')).parent
    for item in entries:
        parts = PurePosixPath(item.filename.replace('\\', '/')).parts
        if any(part.casefold() in {'overrides', 'client-overrides', 'server-overrides', 'mods', 'plugins', 'runtime'} for part in parts):
            continue
        if (parts and (parts[-1].lower().endswith(('.bat', '.cmd', '.sh', '.jar', '.phar'))
                       or parts[-1].lower() in {'win_args.txt', 'unix_args.txt', 'bedrock_server.exe'})):
            return
    try:
        record = json.loads(package.read(index))
        if not isinstance(record, dict) or record.get('formatVersion') != 1 or record.get('game') != 'minecraft':
            return
        deps = record.get('dependencies', {})
        mc = str(deps.get('minecraft', '未声明'))[:40]
        loaders = ' / '.join(key + ' ' + str(deps[key])[:40] for key in ('forge', 'neoforge', 'fabric-loader', 'quilt-loader') if key in deps)
        files = record.get('files', [])
        count = len(files) if isinstance(files, list) else 0
        unknown = sum(not isinstance(f, dict) or 'server' not in f.get('env', {}) for f in files) if isinstance(files, list) else 0
    except (ValueError, KeyError, TypeError):
        raise ArchiveInstallError('发现 Modrinth 整合包清单，但内容无法读取；请核对原始整合包。') from None
    raise ArchiveInstallError('已识别为尚未安装的 Modrinth 模组整合包（Minecraft ' + mc + ('，' + loaders if loaders else '')
        + '），不是已安装的服务端 ZIP。清单有 ' + str(count) + ' 项下载文件，未发现服务端启动入口。'
        + ('其中 ' + str(unknown) + ' 项未声明服务端适用性。' if unknown else '')
        + '“生成七章专属启动文件”用于适配已有入口，不能直接完成客户端/模组清单转服。'
        + '请使用作者提供的服务端包，或先完成核心安装与模组服务端兼容检查后导入；原压缩包未修改。')


def checked_destination(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ArchiveInstallError("安装目录必须使用完整路径。")
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or (resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir()))):
        raise ArchiveInstallError("请选择新的空文件夹，已有服务器不会被覆盖。")
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")).resolve()
    if resolved == windows or windows in resolved.parents:
        raise ArchiveInstallError("不能安装到 Windows 系统目录。")
    for item in (path, *path.parents):
        if item.exists() and (item.is_symlink() or getattr(item, "is_junction", lambda: False)()):
            raise ArchiveInstallError("安装目录不能包含目录联接或符号链接。")
    return resolved


def safe_name(name):
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or name.startswith(("/", "\\")):
        raise ArchiveInstallError("压缩包包含无效路径。")
    for part in parts:
        stem = part.split(".", 1)[0].upper()
        if part in {".", ".."} or part.endswith((" ", ".")) or any(char in part for char in ':<>"|?*') or any(ord(c) < 32 for c in part):
            raise ArchiveInstallError("压缩包包含不安全的路径。")
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
            raise ArchiveInstallError("压缩包包含 Windows 保留设备名。")
    return parts


def jar_manifest(jar):
    """Read unfolded JAR attributes, without loading any archive code."""
    with zipfile.ZipFile(jar) as file:
        # Signed Forge JARs have large per-entry signature sections. Only the
        # bounded main section defines the executable's identity; attributes
        # from a later Name section must never override Main-Class.
        with file.open("META-INF/MANIFEST.MF") as stream:
            raw = stream.read(65537)
        normalized = raw.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        main = normalized.split(b"\n\n", 1)[0]
        if len(raw) > 65536 and b"\n\n" not in normalized:
            raise ArchiveInstallError("服务端 JAR 清单主属性超过允许大小。")
        data = main.decode("utf-8", "replace")
    # JAR attributes may wrap at 72 bytes; continuation lines begin with a space.
    data = data.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    data = re.sub(r"\n ", "", data)
    return dict(line.split(": ", 1) for line in data.splitlines() if ": " in line)


def _minecraft_version(value):
    return value if isinstance(value, str) and re.fullmatch(r"(?:1\.\d{1,2}(?:\.\d{1,2})?|2[6-9]\.\d{1,2}(?:\.\d{1,2})?)", value) else ""


def _filename_version(name):
    # The known server Main-Class is checked before a filename is used as evidence.
    match = re.match(r"(?:forge|neoforge|minecraft[_-]?server|server|fabric[-_]server(?:[-_]launch)?|catserver|spigot|craftbukkit|paper|purpur|folia|arclight|mohist|magma|sponge)[-_.]?(1\.\d{1,2}(?:\.\d{1,2})?)(?=[-_.]|$)", name, re.I)
    return match.group(1) if match else ""


def _paperclip_version(jar):
    """Recognize Paper's known modern wrapper, never arbitrary bootstrap code.

    Check the wrapper entry, delegated Bukkit main, version metadata and bundled
    target/patch descriptors together. This is format validation, not a claim
    that an unsigned user-supplied JAR is trusted; import never executes it.
    """
    try:
        with zipfile.ZipFile(jar) as package:
            def text(name):
                if package.getinfo(name).file_size > 65536:
                    raise ValueError("metadata too large")
                return package.read(name).decode("utf-8-sig").strip()
            if package.getinfo(PAPERCLIP_MAIN.replace(".", "/") + ".class").file_size == 0:
                raise ValueError("missing wrapper class")
            if text("META-INF/main-class") != "org.bukkit.craftbukkit.Main":
                raise ValueError("unsupported delegated main")
            record = json.loads(text("version.json"))
            version = _minecraft_version(record.get("id")) if isinstance(record, dict) else ""
            rows = text("META-INF/versions.list").splitlines()
            fields = rows[0].split("\t") if len(rows) == 1 else []
            if (not version or len(fields) != 3 or fields[1] != version
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0])):
                raise ValueError("conflicting Minecraft versions")
            parts = safe_name(fields[2])
            if len(parts) != 2 or parts[0] != version or not parts[1].endswith(".jar"):
                raise ValueError("invalid target path")
            from native_server_install import java_requirement
            required = java_requirement(version)
            if ("java_version" in record and (type(record["java_version"]) is not int
                    or (required["known"] and record["java_version"] != required["major"]))):
                raise ValueError("conflicting Java requirement")
            target = "META-INF/versions/" + fields[2]
            if target not in package.namelist():
                # Official Paperclip distributes a patch instead of the patched
                # server. Match its output hash and path, and require patch data.
                matches = [row.split("\t") for row in text("META-INF/patches.list").splitlines()
                           if row.startswith("versions\t")]
                matches = [row for row in matches if len(row) == 7 and row[3].lower() == fields[0].lower()
                           and row[6] == fields[2]]
                if len(matches) != 1:
                    raise ValueError("missing unique server patch")
                patch = "/".join(safe_name(matches[0][5]))
                if package.getinfo("META-INF/versions/" + patch).file_size == 0:
                    raise ValueError("empty server patch")
                context = text("META-INF/download-context").split("\t")
                if len(context) != 3 or not re.fullmatch(r"[0-9a-fA-F]{64}", context[0]):
                    raise ValueError("invalid original-server descriptor")
            elif package.getinfo(target).file_size == 0:
                raise ValueError("empty bundled server")
            return version
    except (KeyError, zipfile.BadZipFile, OSError, ValueError, UnicodeError) as error:
        raise ArchiveInstallError("Paperclip 服务端的主类、版本或补丁资料不完整或不一致，请使用完整的官方 Paper 服务端文件。") from error


def _jar_version_evidence(jar, root):
    evidence = []
    relative = jar.relative_to(root).as_posix()
    filename = _filename_version(jar.stem)
    if filename:
        evidence.append({"source": relative + " (filename)", "version": filename})
    try:
        manifest = jar_manifest(jar)
        implementation = manifest.get("Implementation-Version", "")
        main = manifest.get("Main-Class", "").strip()
        if main in JAVA_SERVER_MAINS and JAVA_SERVER_MAINS[main] in {"arclight", "mohist", "magma", "sponge"}:
            identified = re.search(r"(?:^|[-_])(1\.\d+(?:\.\d+)?)(?:[-_]|$)", implementation)
            if identified:
                evidence.append({"source": relative + "!MANIFEST.MF:Implementation-Version", "version": identified[1]})
        if main == PAPERCLIP_MAIN:
            value = _paperclip_version(jar)
            evidence.append({"source": relative + "!Paperclip:version.json+versions.list", "version": value})
        match = re.match(r"git-CatServer-(1\.\d+(?:\.\d+)?)-", implementation) if main == CATSERVER_MAIN else re.match(r"(1\.\d+(?:\.\d+)?)-\d", implementation) if main in LEGACY_FORGE_MAINS else None
        if match:
            evidence.append({"source": relative + "!MANIFEST.MF:Implementation-Version", "version": match.group(1)})
        for attribute in ("Minecraft-Version", "MinecraftVersion", "Fabric-Game-Version"):
            value = _minecraft_version(manifest.get(attribute, ""))
            if value:
                evidence.append({"source": relative + "!MANIFEST.MF:" + attribute, "version": value})
        with zipfile.ZipFile(jar) as package:
            if "version.json" in package.namelist():
                if package.getinfo("version.json").file_size > 65536:
                    raise ArchiveInstallError("Minecraft 版本资料超过允许大小。")
                record = json.loads(package.read("version.json"))
                value = _minecraft_version(record.get("id")) if isinstance(record, dict) else ""
                if value:
                    evidence.append({"source": relative + "!version.json", "version": value})
    except (KeyError, zipfile.BadZipFile, OSError, ValueError) as error:
        if isinstance(error, ArchiveInstallError):
            raise
    return evidence


def _version_key(version):
    values = tuple(map(int, version.split(".")))
    return values + (0,) * (3 - len(values))


def detect_minecraft_version(root, core):
    """Use the chosen entry's evidence, never every installed loader version."""
    root = Path(root)
    platform, kind, payload, loader_version = core
    evidence = []
    if kind == "jar":
        evidence.extend(_jar_version_evidence(root / payload, root))
        manifest = jar_manifest(root / payload)
        if manifest.get("Main-Class", "").strip() == CATSERVER_STANDARD_MAIN:
            # Standard CatServer launches with -jar. Its own declared vanilla /
            # Forge dependencies identify the MC release, not unrelated backups.
            for reference in manifest.get("Class-Path", "").split():
                dependency = _classpath_reference(root.resolve(), (root / payload).resolve(), reference)
                if not dependency.is_file() or dependency.suffix.lower() != ".jar":
                    continue
                try:
                    main = jar_manifest(dependency).get("Main-Class", "").strip()
                except (KeyError, zipfile.BadZipFile, OSError):
                    continue
                if main in VANILLA_MAINS | LEGACY_FORGE_MAINS:
                    for item in _jar_version_evidence(dependency, root.resolve()):
                        evidence.append({"source": payload + "!MANIFEST.MF:Class-Path -> " + item["source"], "version": item["version"]})
    if platform in {"forge", "catserver", "arclight", "mohist", "magma"}:
        versions = [loader_version] if kind == "args" else []
        if kind == "jar" and not evidence:
            installed = [p.name for p in (root / "libraries/net/minecraftforge/forge").glob("*") if p.is_dir()]
            # A lone legacy artifact can identify an otherwise unversioned JAR.
            # Several old releases are not evidence about which one it uses.
            if len(installed) == 1:
                versions = installed
        for artifact in versions:
            match = re.match(r"(1\.\d{1,2}(?:\.\d{1,2})?)-\d", artifact)
            if match:
                evidence.append({"source": "forge artifact " + artifact, "version": match.group(1)})
    elif platform == "neoforge" and kind == "args":
        match = re.fullmatch(r"(20|21)\.(\d+)\.\d+(?:-beta)?", loader_version)
        if match:
            patch = int(match.group(2))
            value = "1." + match.group(1) + ("." + str(patch) if patch else "")
            evidence.append({"source": "neoforge artifact " + loader_version, "version": value})
    # Legacy Forge/Fabric packages commonly contain their required vanilla JAR.
    # A backup of a different release is another possible launch target, not
    # contradictory evidence about the selected loader's own identity.
    if platform in {"forge", "catserver", "arclight", "mohist", "magma", "neoforge", "fabric", "quilt"}:
        companions = []
        for jar in root.glob("*.jar"):
            try:
                if jar_manifest(jar).get("Main-Class", "").strip() in VANILLA_MAINS:
                    companions.extend(_jar_version_evidence(jar, root))
            except (KeyError, zipfile.BadZipFile, OSError):
                continue
        current = {_version_key(item["version"]) for item in evidence}
        companion_versions = {_version_key(item["version"]) for item in companions}
        if current:
            evidence.extend(item for item in companions if _version_key(item["version"]) in current)
        elif len(companion_versions) == 1:
            evidence.extend(companions)
    versions = {_version_key(item["version"]) for item in evidence}
    if len(versions) > 1:
        raise ArchiveInstallError("服务端核心中的 Minecraft 版本信息冲突，请整理为同一版本后再导入。")
    return (evidence[0]["version"] if evidence else ""), evidence


def _enumerate_cores(root):
    """Enumerate known server descriptors, without interpreting arbitrary JARs."""
    choices = []
    for platform, relative in (("neoforge", "libraries/net/neoforged/neoforge"), ("forge", "libraries/net/minecraftforge/forge")):
        for args in (root / relative).glob("*/win_args.txt"):
            if args.is_file():
                choices.append((platform, "args", args.relative_to(root).as_posix(), args.parent.name))
    for jar in root.glob("*.jar"):
        try:
            manifest = jar_manifest(jar)
            main = manifest.get("Main-Class", "").strip()
            if main in VANILLA_MAINS:
                choices.append(("vanilla", "jar", jar.name, ""))
            elif main in BUKKIT_MAINS:
                brand = "spigot" if "spigot" in manifest.get("Implementation-Title", "").lower() else "bukkit"
                choices.append((brand, "jar", jar.name, ""))
            elif main == PAPERCLIP_MAIN:
                _paperclip_version(jar)
                brand = "paper"
                with zipfile.ZipFile(jar) as package:
                    names = set(package.namelist())
                    # Branding is read from the artifact itself, never guessed from a renamed file.
                    title = manifest.get("Implementation-Title", "").lower()
                    versions_text = package.read("META-INF/versions.list").decode("utf-8", "replace").lower()
                    if "/purpur-" in versions_text or "purpur" in title or "META-INF/maven/org.purpurmc.purpur/purpur-api/pom.properties" in names:
                        brand = "purpur"
                    elif "/folia-" in versions_text or "folia" in title:
                        brand = "folia"
                choices.append((brand, "jar", jar.name, ""))
            elif main in JAVA_SERVER_MAINS:
                brand = JAVA_SERVER_MAINS[main]
                if brand == "bungeecord" and "waterfall" in manifest.get("Implementation-Title", "").lower():
                    brand = "waterfall"
                choices.append((brand, "jar", jar.name, manifest.get("Implementation-Version", "")[:80]))
            elif re.fullmatch(r"net\.fabricmc\.(?:loader\.(?:impl\.)?launch\.server\.FabricServerLauncher|installer\.ServerLauncher)", main):
                choices.append(("fabric", "jar", jar.name, ""))
            elif main in {CATSERVER_MAIN, CATSERVER_STANDARD_MAIN}:
                choices.append(("catserver", "jar", jar.name, manifest.get("Implementation-Version", "")))
            elif main in LEGACY_FORGE_MAINS:
                choices.append(("forge", "jar", jar.name, manifest.get("Implementation-Version", "")))
        except (KeyError, zipfile.BadZipFile, OSError):
            continue
    if (root / "bedrock_server.exe").is_file():
        choices.append(("bedrock", "native", "bedrock_server.exe", ""))
    if (root / "PocketMine-MP.phar").is_file():
        choices.append(("pocketmine", "php", "PocketMine-MP.phar", ""))
    return sorted(set(choices), key=lambda core: tuple(value.casefold() for value in core))


def _core_fingerprint(root, core):
    path = _relative_file(root, core[2], "服务端启动入口")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _selection_record(root, core):
    return {"platform": core[0], "kind": core[1], "entry": core[2], "loader_version": core[3],
            "sha256": _core_fingerprint(root, core)}


def _choice(root, core, server_path=".", reason="检测到已识别的服务端核心；需要确认使用哪一个启动目标。"):
    identity = _selection_record(root, core)
    digest = hashlib.sha256(json.dumps([server_path, identity], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]
    try:
        version = detect_minecraft_version(root, core)[0]
    except ArchiveInstallError as error:
        version = ""
        reason += " 版本尚不能确认：" + str(error)
    return {"id": "core-" + digest, "server_path": server_path, **{key: value for key, value in identity.items() if key != "sha256"},
            "minecraft_version": version, "reason": reason}


def _read_json_record(path, label, limit=65536):
    try:
        if path.stat().st_size > limit:
            raise ValueError("too large")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except (OSError, ValueError) as error:
        raise ArchiveInstallError(label + " JSON 无效。") from error


def _literal_script_choice(root, choices):
    """Recognize simple Java entry lines only; CMD is never executed or evaluated."""
    scripts = sorted([*root.glob("*.bat"), *root.glob("*.cmd")], key=lambda item: item.name.casefold())
    if len(scripts) > 32:
        return None
    references = set()
    for script in scripts:
        if script.name.casefold().startswith("qizhang-"):
            # Generated launchers contain variables; persistent selection is
            # validated separately and remains portable after moving the folder.
            continue
        if script.stat().st_size > 131072:
            return None
        raw = script.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", "replace")
        script_refs = set()
        uncertain = False
        for original in text.splitlines():
            line = original.strip().lstrip("@").strip()
            if not line or re.match(r"(?i)^(?:rem(?:\s|$)|::|echo(?:\s|$))", line):
                continue
            if re.fullmatch(r'(?i)(?:setlocal(?:\s+\w+)*|endlocal|pause|exit\s+/b(?:\s+(?:\d+|%errorlevel%))?|cd\s+/d\s+"%~dp0")', line):
                continue
            # No labels, branches, substitutions, pipes, command chains or
            # changing directories: a textual match in such a script is not proof.
            if any(char in line for char in "&|<>^!") or line.startswith(":"):
                uncertain = True
                break
            tokens = re.findall(r'(?:[^\s"]+|"[^"\r\n]*")+', line)
            if line.count('"') % 2 or not tokens:
                uncertain = True
                break
            tokens = [token.replace('"', '') for token in tokens]
            executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if executable not in {"java", "java.exe"} or "%" in tokens[0]:
                uncertain = True
                break
            arguments = tokens[1:]
            if any("%" in token and token != "%*" for token in arguments):
                uncertain = True
                break
            matched = set()
            for index, token in enumerate(arguments):
                prefix = arguments[:index]
                if any(not (arg.startswith(("-Xms", "-Xmx", "-XX:", "-D")) or arg.casefold() in {"@user_jvm_args.txt", "-ea", "-da"}) for arg in prefix):
                    continue
                if token == "-jar" and index + 1 < len(arguments):
                    target = arguments[index + 1].replace("\\", "/")
                    matched.update(core for core in choices if core[1] == "jar" and core[2].casefold() == target.removeprefix("./").casefold())
                elif token.startswith("@"):
                    target = token[1:].replace("\\", "/")
                    matched.update(core for core in choices if core[1] == "args" and core[2].casefold() == target.removeprefix("./").casefold())
            if not matched and arguments not in (["-version"], ["--version"]):
                uncertain = True
                break
            script_refs.update(matched)
        if uncertain:
            # A second script may select an alternative via variables. Do not
            # silently prefer the one script that happened to be easy to parse.
            return None
        references.update(script_refs)
    return next(iter(references)) if len(references) == 1 else None


def _literal_jar_parameters(root, core):
    """Copy a selected JAR's unambiguous literal call, not the batch program."""
    if core[1] != "jar":
        return None
    scripts = sorted([*root.glob("*.bat"), *root.glob("*.cmd")], key=lambda path: path.name.casefold())
    if len(scripts) > 32:
        return None
    matches = []
    for script in scripts:
        if script.name.casefold().startswith("qizhang-"):
            continue
        if script.stat().st_size > 131072:
            return None
        raw = script.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", "replace")
        for original in text.splitlines():
            line = original.strip().lstrip("@").strip()
            if not line or re.match(r"(?i)^(?:rem(?:\s|$)|::|echo(?:\s|$))", line):
                continue
            tokens = re.findall(r'(?:[^\s"]+|"[^"\r\n]*")+', line)
            if not tokens:
                continue
            tokens = [token.replace('"', '') for token in tokens]
            executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if executable not in {"java", "java.exe"}:
                if "-jar" in tokens and any(token.replace("\\", "/").removeprefix("./").casefold() == core[2].casefold() for token in tokens):
                    return None  # A conditional/call/variable command is ambiguous.
                continue
            # Only a standalone literal Java command is evidence. Conditional
            # and variable commands are never evaluated to invent parameters.
            if line.count('"') % 2 or any(char in line for char in "&|<>^!") or "%" in tokens[0]:
                return None
            arguments = tokens[1:]
            if arguments and arguments[-1] == "%*":
                arguments = arguments[:-1]
            if any("%" in token for token in arguments):
                return None
            if arguments.count("-jar") != 1:
                continue
            index = arguments.index("-jar")
            if index + 1 >= len(arguments):
                return None
            target = arguments[index + 1].replace("\\", "/").removeprefix("./")
            if target.casefold() != core[2].casefold():
                continue
            jvm, game = arguments[:index], arguments[index + 2:]
            if any(not arg.startswith(("-Xms", "-Xmx", "-XX:", "-D")) or arg.startswith("-Dqizhang.panel.server_id") for arg in jvm):
                return None
            _argument_list(jvm, "原启动脚本 JVM 参数")
            _argument_list(game, "原启动脚本游戏参数")
            matches.append({"jvm_args": jvm, "game_args": game, "source": script.name})
    signatures = {(tuple(item["jvm_args"]), tuple(item["game_args"])) for item in matches}
    return matches[0] if len(signatures) == 1 else None


def _launch_candidates(root):
    choices = _enumerate_cores(root)
    if not choices:
        return [], ""
    saved_choice = None
    metadata = root / "qizhang-import.json"
    if metadata.exists():
        saved = _read_json_record(metadata, "七章导入记录", 2 * 1024**2).get("core_selection")
        if saved is not None:
            selected = [core for core in choices if _selection_record(root, core) == saved]
            if len(selected) != 1:
                raise ArchiveSelectionRequired([_choice(root, core) for core in choices], "之前选择的核心已变化，请重新选择服务器启动目标。")
            saved_choice = selected[0]
    manifest = root / LAUNCH_MANIFEST
    if manifest.exists():
        declared = _read_json_record(manifest, "服务端启动配置")
        selected = [core for core in choices if core[1] == "jar" and core[2] == declared.get("core_jar") and (core[0] == declared.get("platform") or (core[0] == "catserver" and declared.get("platform") == "forge"))]
        if len(selected) != 1:
            raise ArchiveInstallError("启动配置与已识别的服务端核心不匹配，请核对声明的核心入口。")
        if saved_choice and selected[0] != saved_choice:
            raise ArchiveInstallError("启动清单与之前明确选择的核心不一致，请核对后重新导入；不会套用其他核心的启动参数。")
        load_launch_manifest(root, selected[0])  # Full schema, main class and classpath validation.
        return selected, "已验证七章启动清单，明确指定这个核心及其启动参数。"
    if saved_choice:
        return [saved_choice], "沿用之前明确选择的启动入口，已重新验证核心文件。"
    script_choice = _literal_script_choice(root, choices)
    if not script_choice:
        from native_startup_import import discover_startup_scripts
        parsed = discover_startup_scripts(root, choices)
        inferred = {tuple(item["core"]) for item in parsed["profiles"]}
        if len(inferred) == 1 and not parsed.get("unsupported"):
            script_choice = next(iter(inferred))
    if script_choice:
        return [script_choice], "原启动脚本中的字面 Java 命令唯一指向这个入口；这里只识别入口，额外参数请在服务器启动设置核对。"
    loaders = [core for core in choices if core[0] in {"forge", "neoforge", "fabric"}]
    if loaders:
        pruned = []
        for core in choices:
            dependency = False
            if core[0] == "vanilla" and jar_manifest(root / core[2]).get("Main-Class", "").strip() in VANILLA_MAINS:
                version = detect_minecraft_version(root, core)[0]
                loader_versions = [detect_minecraft_version(root, loader)[0] for loader in loaders]
                dependency = any(version and item and _version_key(version) == _version_key(item) for item in loader_versions)
                if len(loaders) == 1 and len(choices) == 2 and (not version or not loader_versions[0]):
                    dependency = True
            if not dependency:
                pruned.append(core)
        choices = pruned
    return choices, "检测到多个可识别入口，启动脚本或清单没有提供唯一、可验证的选择。" if len(choices) > 1 else "已识别唯一启动目标，相关原版依赖文件保留。"


def detect_core(root):
    """Return the historical tuple/None API, or offer explicit safe choices."""
    root = Path(root)
    choices, reason = _launch_candidates(root)
    if len(choices) > 1:
        raise ArchiveSelectionRequired([_choice(root, core, reason=reason) for core in choices])
    return choices[0] if choices else None


def unrecognized_details(staging):
    """Bounded, non-executing diagnostics; never include script contents/secrets."""
    staging = Path(staging)
    scripts, args, cores = [], [], []
    examined = 0
    for parent, dirs, files in os.walk(staging):
        base = Path(parent)
        depth = len(base.relative_to(staging).parts)
        dirs[:] = [d for d in dirs if d.casefold() not in {'mods', 'plugins', 'runtime', 'world', 'backups'}] if depth < 8 else []
        for name in files:
            examined += 1
            if examined > 6000:
                break
            file = base / name
            relative = file.relative_to(staging).as_posix()
            if file.suffix.casefold() in {'.bat', '.cmd', '.sh'} and len(scripts) < 5:
                scripts.append(relative)
            if name.casefold() in {'win_args.txt', 'unix_args.txt'} and len(args) < 5:
                args.append(relative)
            if file.suffix.casefold() == '.jar' and depth <= 4 and len(cores) < 6:
                try:
                    main = jar_manifest(file).get('Main-Class', '').strip()
                    cores.append(relative + ' → ' + (main[:160] if main else '没有 Main-Class'))
                except (KeyError, OSError, ValueError, zipfile.BadZipFile):
                    cores.append(relative + ' → JAR 清单无法读取')
        if examined > 6000:
            break
    return (' 识别诊断（仅查看文件，未执行）：启动脚本：' + ('；'.join(scripts) or '未找到')
            + '。参数入口：' + ('；'.join(args) or '未找到')
            + '。候选 JAR：' + ('；'.join(cores) or '未找到')
            + '。请保留原压缩包，并将此诊断与原启动脚本一并提供以适配。')


def find_server_root(staging, selected_core=None):
    staging = Path(staging)
    # Limit inference to plausible server roots; never mistake a JAR inside mods for a server.
    candidates = {staging}
    candidates.update(p.parent for p in staging.rglob("server.properties"))
    candidates.update(p.parent for p in staging.rglob("bedrock_server.exe"))
    candidates.update(p.parent for p in staging.rglob("PocketMine-MP.phar"))
    candidates.update(p.parent for p in staging.rglob("run.bat"))
    candidates.update(p.parent for p in staging.rglob("fabric-server-launch.jar"))
    candidates.update(p.parent for p in staging.rglob("fabric-server-launcher.jar"))
    candidates.update(p.parent for p in staging.rglob("server.jar"))
    candidates.update(p.parent for p in staging.rglob("*.jar") if len(p.relative_to(staging).parts) <= 5)
    for args in staging.rglob("win_args.txt"):
        parts = args.relative_to(staging).parts
        if len(parts) >= 6 and tuple(part.casefold() for part in parts[-6:-2]) in {
                ("libraries", "net", "neoforged", "neoforge"), ("libraries", "net", "minecraftforge", "forge")}:
            candidates.add(args.parents[5])
    found = []
    for candidate in sorted(candidates, key=lambda item: item.relative_to(staging).as_posix().casefold()):
        relative = candidate.relative_to(staging)
        if len(relative.parts) > 4 or any(p.lower() in {"mods", "plugins", "libraries", "backups", "world", "runtime", "maintenance-sources", ".minecraft_versions", ".minecraft", ".fabric", "versions"} for p in relative.parts):
            continue
        problem = None
        try:
            cores, reason = _launch_candidates(candidate)
        except ArchiveSelectionRequired:
            # A saved selection from an earlier import may be stale. Enumerate
            # every current candidate so the new import can explicitly replace it.
            cores, reason = _enumerate_cores(candidate), "之前选择的入口已变化，需要重新选择。"
        except ArchiveInstallError as error:
            # A broken manifest in another bundled server must not prevent an
            # explicit choice of a valid server. It remains visible, never
            # silently auto-selected or imported without its launch contract.
            cores, reason, problem = _enumerate_cores(candidate), "此目标的启动配置需要修正：" + str(error), error
        for core in cores:
            found.append((candidate, core, _choice(candidate, core, relative.as_posix(), reason), problem))
    if not found:
        raise ArchiveInstallError("面板尚未识别到唯一可绑定的服务端启动格式，不能据此判定压缩包缺少核心。" + unrecognized_details(staging))
    if selected_core is not None:
        selected = [item for item in found if isinstance(selected_core, str) and item[2]["id"] == selected_core]
        if len(selected) != 1:
            raise ArchiveSelectionRequired([item[2] for item in found], "压缩包中的启动目标已变化或选择无效，请重新选择。")
        if selected[0][3]:
            raise selected[0][3]
        return selected[0][:2]
    if len(found) > 1:
        raise ArchiveSelectionRequired([item[2] for item in found])
    if found[0][3]:
        raise found[0][3]
    return found[0][:2]


def _relative_file(root, value, label):
    if not isinstance(value, str) or not value or any(c in value for c in '%!\r\n"&|<>^;'):
        raise ArchiveInstallError(label + "必须是安全的包内相对路径。")
    parts = safe_name(value)
    path = root.joinpath(*parts)
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ArchiveInstallError(label + "不存在或超出服务器目录：" + value)
    return path


def _argument_list(value, label):
    if not isinstance(value, list) or len(value) > 128 or any(
            not isinstance(arg, str) or not arg or len(arg) > 2048 or any(ord(c) < 32 for c in arg)
            for arg in value):
        raise ArchiveInstallError(label + "必须是有效的参数字符串数组。")
    return value


def _bundled_java_location(root, relative):
    if not isinstance(relative, str) or not relative or any(c in relative for c in '%!\r\n"&|<>^;'):
        raise ArchiveInstallError("随包 Java 必须是安全的包内相对路径。")
    path = root.joinpath(*safe_name(relative))
    if not path.resolve().is_relative_to(root.resolve()):
        raise ArchiveInstallError("随包 Java 路径超出服务器目录。")
    if path.name.lower() != "java.exe" or path.parent.name.lower() != "bin":
        raise ArchiveInstallError("随包 Java 路径必须指向 bin/java.exe。")
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ArchiveInstallError("随包 Java 路径不能包含链接。")
    return path


def inspect_bundled_java(root, relative):
    """Inspect release metadata only. Never execute a program from an import."""
    java = _bundled_java_location(root, relative)
    if not java.is_file():
        raise ArchiveInstallError("随包 Java 可执行文件不存在。")
    home = java.parent.parent
    release = home / "release"
    # A full Java 8 JDK may also include jre/bin/java.exe while its release
    # metadata belongs to the outer JDK home.
    if not release.is_file() and home.name.lower() == "jre":
        release = home.parent / "release"
    if not release.resolve().is_relative_to(root.resolve()) or release.is_symlink():
        raise ArchiveInstallError("随包 Java 的 release 路径不安全。")
    try:
        if release.stat().st_size > 65536:
            raise ArchiveInstallError("随包 Java 的 release 版本资料超过允许大小。")
        text = release.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise ArchiveInstallError("随包 Java 缺少可读取的 release 版本声明文件。") from error
    values = {}
    for key in ("JAVA_VERSION", "OS_ARCH", "OS_NAME"):
        matches = re.findall(r"^" + key + r'="([^"\r\n]*)"\s*$', text, re.M)
        if len(matches) != 1:
            raise ArchiveInstallError("随包 Java 的 release 缺少或重复声明 " + key + "。")
        values[key] = matches[0]
    match = re.fullmatch(r"(?:1\.)?(\d+)(?:[._+\-][^\r\n]*)?", values["JAVA_VERSION"])
    if not match or len(values["JAVA_VERSION"]) > 128:
        raise ArchiveInstallError("随包 Java 的版本声明无效。")
    if values["OS_ARCH"].lower() not in {"amd64", "x86_64"}:
        raise ArchiveInstallError("随包 Java 不是适用的 Windows x64（64 位）版本。")
    if values["OS_NAME"].lower() != "windows":
        raise ArchiveInstallError("随包 Java 不是 Windows 版本。")
    return {"path": java.relative_to(root).as_posix(), "major": int(match.group(1)), "bits": 64,
            "version": values["JAVA_VERSION"], "release_path": release.relative_to(root).as_posix(),
            "validation": "bundled-release-static-only"}


def discover_bundled_java(root, required_major, preferred_path="", minimum=False):
    """Bounded scan of plausible runtime folders, preserving all imported files."""
    report = {"candidates": [], "rejected": [], "scanned_directories": 0,
              "skipped_deep_directories": 0, "scan_limit_reached": False}
    paths = set()
    if preferred_path:
        # Validate an explicit contract path even if the file is missing.
        _bundled_java_location(root, preferred_path)
        paths.add(preferred_path.replace("\\", "/"))
    excluded = {"mods", "plugins", "backups", "world", "world_nether", "world_the_end", ".git", "maintenance-sources"}
    for directory, dirs, files in os.walk(root, followlinks=False):
        current = Path(directory)
        report["scanned_directories"] += 1
        if report["scanned_directories"] > MAX_JAVA_DIRECTORIES:
            report["scan_limit_reached"] = True
            break
        depth = len(current.relative_to(root).parts)
        allowed = []
        for name in sorted(dirs, key=str.casefold):
            child = current / name
            if name.lower() in excluded or child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                continue
            if depth >= MAX_JAVA_DEPTH - 1:
                report["skipped_deep_directories"] += 1
                continue
            allowed.append(name)
        dirs[:] = allowed
        if current.name.lower() == "bin":
            paths.update((current / name).relative_to(root).as_posix()
                         for name in files if name.lower() == "java.exe")
    for relative in sorted(paths, key=str.casefold):
        try:
            info = inspect_bundled_java(root, relative)
            if required_major is None:
                raise ArchiveInstallError("Minecraft 版本未知，不能自动判断随包 Java 是否兼容。")
            if info["major"] < required_major if minimum else info["major"] != required_major:
                raise ArchiveInstallError(f"随包为 Java {info['major']}，此服务器需要 Java {required_major}。")
            if len(report["candidates"]) < MAX_JAVA_REPORT_ITEMS:
                report["candidates"].append(info)
        except ArchiveInstallError as error:
            if len(report["rejected"]) < MAX_JAVA_REPORT_ITEMS:
                report["rejected"].append({"path": relative, "reason": str(error)})
    def preference(info):
        numbers = tuple(-int(value) for value in re.findall(r"\d+", info["version"]))
        numbers += (0,) * max(0, 8 - len(numbers))
        return (info["path"].casefold() != preferred_path.replace("\\", "/").casefold(),
                numbers, len(PurePosixPath(info["path"]).parts), info["path"].casefold())
    report["candidates"].sort(key=preference)
    return report


def copy_outer_bundled_java(staging, server, info):
    """Copy an enclosing ZIP's sibling runtime into this server, never link it."""
    checked = inspect_bundled_java(staging, info["path"])
    java = staging.joinpath(*safe_name(checked["path"]))
    runtime = staging.joinpath(*safe_name(checked["release_path"])).parent
    source = runtime.resolve()
    if (source == staging.resolve() or not source.is_relative_to(staging.resolve())
            or source == server.resolve() or source in server.resolve().parents
            or source.is_relative_to(server.resolve())):
        raise ArchiveInstallError("外层随包 Java 必须处于本次压缩包内独立的运行时文件夹，不能与服务器目录相互包含。")
    java_home = java.parent.parent
    homes = [java_home, java_home / "jre"] if checked["major"] == 8 else [java_home]
    vm_dll = any((home / "bin/jvm.dll").is_file() or any(path.is_file() for path in (home / "bin").glob("*/jvm.dll")) for home in homes)
    library = any((home / "lib" / ("rt.jar" if checked["major"] == 8 else "modules")).is_file() for home in homes)
    if not vm_dll or not library:
        raise ArchiveInstallError("外层 Java 缺少运行库（jvm.dll 或 lib/rt.jar、lib/modules），不会只复制 java.exe。")
    # ZIP extraction rejected links already; repeat the boundary check before a
    # recursive copy so a changed staging tree cannot import external files.
    for directory, dirs, files in os.walk(source, followlinks=False):
        for item in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
            if (item.is_symlink() or getattr(item, "is_junction", lambda: False)()
                    or not item.resolve().is_relative_to(source)):
                raise ArchiveInstallError("外层 Java 运行时包含链接或越界文件。")
    base = server / "qizhang-bundled-java"
    if (base.exists() and not base.is_dir()) or base.is_symlink() or getattr(base, "is_junction", lambda: False)():
        raise ArchiveInstallError("qizhang-bundled-java 不是安全的服务器内目录。")
    target = base / ("java-" + str(checked["major"]) + "-" + uuid.uuid4().hex[:12])
    if not target.resolve().is_relative_to(server.resolve()) or target.exists():
        raise ArchiveInstallError("外层 Java 复制目标无效，已有文件不会被覆盖。")
    shutil.copytree(source, target)
    copied_java = target / java.relative_to(runtime)
    copied = inspect_bundled_java(server, copied_java.relative_to(server).as_posix())
    copied["copied_from_archive"] = checked["path"]
    return copied


def _legacy_catserver_profile(root, core):
    """Recognize the shipped EeryFrank 1.12.2 package, never evaluate its C#/EXE/scripts."""
    error = "已识别 CatServer 核心，但未识别可安全保留完整 classpath 的启动格式。请保留原启动器/随包 Java 和 maintenance-sources，或提供明确的 qizhang-server-launch.json。"
    expected_core = "CatServer-4168d848-universal.jar"
    source = root / "maintenance-sources/server-launcher/LauncherCore.cs"
    if core[2] != expected_core or not source.is_file() or source.stat().st_size > 256 * 1024:
        raise ArchiveInstallError(error)
    manifest = jar_manifest(root / expected_core)
    if manifest.get("Implementation-Version", "") != "git-CatServer-1.12.2-4168d848":
        raise ArchiveInstallError(error)
    with zipfile.ZipFile(root / expected_core) as package:
        if "catserver/server/CatServerLaunch.class" not in package.namelist():
            raise ArchiveInstallError(error)
    text = source.read_text(encoding="utf-8-sig")
    classpath = ["libraries/log4j-api-2.25.3.jar", "libraries/log4j-core-2.25.3.jar",
                 "libraries/lwjgl_util-2.9.4-nightly-20150209.jar", expected_core]
    literal = re.findall(r'public\s+const\s+string\s+ClassPath\s*=\s*"([^"\r\n]*)"\s*;', text)
    expected_command = r'new ProcessStartInfo(java, "-Xms1G -Xmx" + memory + " -XX:+UseG1GC -Dfile.encoding=UTF-8 -Dfml.readTimeout=180 -Dcatserver.skipCheckLibraries=true -Dcatserver.spark.enable=false -cp \"" + ClassPath + "\" catserver.server.CatServerLaunch nogui")'
    if literal != [";".join(classpath)] or expected_command not in text:
        raise ArchiveInstallError(error)
    for relative in classpath:
        _relative_file(root, relative, "CatServer 兼容 Classpath 文件")
    _relative_file(root, "libraries/minecraft_server.1.12.2.jar", "Minecraft 1.12.2 运行库")
    return {"schema_version": 1, "platform": "forge", "minecraft_version": "1.12.2", "java_major": 8,
            "java_path": "runtime/java8/bin/java.exe", "core_jar": expected_core, "main_class": CATSERVER_MAIN,
            "classpath": classpath, "jvm_args": ["-Xms1G", "-Xmx6G", "-XX:+UseG1GC", "-Dfile.encoding=UTF-8",
                "-Dfml.readTimeout=180", "-Dcatserver.skipCheckLibraries=true", "-Dcatserver.spark.enable=false"],
            "game_args": ["nogui"], "command_channel": "default"}


def _has_file_command_bridge(root):
    for path in (root / "plugins").glob("*.jar"):
        try:
            with zipfile.ZipFile(path) as plugin:
                if "local/mc/foundation/PanelCommandBridge.class" in plugin.namelist():
                    return True
        except (OSError, zipfile.BadZipFile):
            continue
    return False


def _classpath_reference(root, source_jar, reference):
    try:
        url = urlsplit(reference)
        decoded = unquote(url.path, encoding="utf-8", errors="strict")
    except ValueError as error:
        raise ArchiveInstallError("Classpath 的 Class-Path 引用无效。") from error
    if url.scheme or url.netloc or url.query or url.fragment or not decoded or decoded.startswith(("/", "\\")) or ":" in decoded or any(ord(char) < 32 for char in decoded):
        raise ArchiveInstallError("Classpath 的 Class-Path 只允许包内相对路径，不能引用远程或绝对位置。")
    target = (source_jar.parent / decoded).resolve()
    if not target.is_relative_to(root):
        raise ArchiveInstallError("Classpath 的 Class-Path 引用超出服务器目录。")
    return target


def _validate_classpath_main(root, classpath, core_jar, main_class):
    """Include bounded manifest Class-Path links; Java resolves those transitively."""
    root = root.resolve()
    selected = (root / core_jar).resolve()
    class_entry = main_class.replace(".", "/") + ".class"
    versioned = re.compile(r"META-INF/versions/([0-9]{1,3})/" + re.escape(class_entry))
    pending = [((root / item).resolve(), 0) for item in classpath]
    visited = set()
    references = 0
    while pending:
        path, depth = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        if depth > 32 or len(visited) > 512:
            raise ArchiveInstallError("Classpath 传递引用超过验证限制，请精简启动清单。")
        if not path.exists():  # Java ignores missing relative Class-Path targets.
            continue
        manifest = {}
        if path.is_dir():
            duplicate = (path / class_entry).is_file()
        else:
            try:
                with zipfile.ZipFile(path) as package:
                    entries = set(package.namelist())
                try:
                    manifest = {key.casefold(): value for key, value in jar_manifest(path).items()}
                except KeyError:
                    pass  # JARs without manifests can still supply the class.
            except zipfile.BadZipFile:
                continue
            duplicate = class_entry in entries or manifest.get("main-class", "").strip() == main_class
            if not duplicate and manifest.get("multi-release", "").strip().casefold() == "true":
                duplicate = any((match := versioned.fullmatch(entry)) and int(match.group(1)) >= 9 for entry in entries)
        if path != selected and duplicate:
            relative = path.relative_to(root).as_posix()
            raise ArchiveInstallError("Classpath 中的 " + relative + " 与所选核心定义了相同的启动主类，无法保证启动选定版本；请从启动清单或库的 Class-Path 移除冲突引用，原文件无需删除。")
        for reference in manifest.get("class-path", "").split():
            references += 1
            if references > 2048:
                raise ArchiveInstallError("Classpath 传递引用超过验证限制，请精简启动清单。")
            target = _classpath_reference(root, path, reference)
            pending.append((target, depth + 1))


def load_launch_manifest(root, core):
    path = root / LAUNCH_MANIFEST
    is_catserver = core[1] == "jar" and jar_manifest(root / core[2]).get("Main-Class", "").strip() == CATSERVER_MAIN
    generated = False
    if not path.exists():
        if is_catserver:
            attributes = jar_manifest(root / core[2])
            # The official standalone bootstrap has its own library installer.
            # The custom packaged C# launcher is a separate classpath contract.
            if (re.fullmatch(r"git-CatServer-1\.\d+(?:\.\d+)?-[0-9a-f]+", attributes.get("Implementation-Version", ""))
                    and not (root / "maintenance-sources/server-launcher/LauncherCore.cs").exists()):
                return None
            data = _legacy_catserver_profile(root, core)
            generated = True
        else:
            return None
    else:
        try:
            if path.stat().st_size > 65536:
                raise ValueError("too large")
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ArchiveInstallError("服务端启动配置 JSON 无效。") from error
    fields = {"schema_version", "platform", "minecraft_version", "java_major", "java_path", "core_jar", "main_class", "classpath", "jvm_args", "game_args", "command_channel"}
    if not isinstance(data, dict) or set(data) != fields or data.get("schema_version") != 1:
        raise ArchiveInstallError("服务端启动配置字段或版本不受支持。")
    if core[1] != "jar" or data["core_jar"] != core[2] or (data["platform"] != core[0] and not (core[0] == "catserver" and data["platform"] == "forge")):
        raise ArchiveInstallError("启动配置与检测到的唯一服务端核心不匹配。")
    actual_main = jar_manifest(root / core[2]).get("Main-Class", "").strip()
    if data["main_class"] != actual_main:
        raise ArchiveInstallError("启动主类必须匹配已识别服务端核心的 JAR 清单。")
    if data["command_channel"] not in {"serverfoundation-file-v1", "default"}:
        raise ArchiveInstallError("启动配置的控制台命令通道不受支持。")
    if data["command_channel"] == "serverfoundation-file-v1" and not _has_file_command_bridge(root):
        raise ArchiveInstallError("启动配置要求 ServerFoundation 文件命令通道，但包内插件未包含 PanelCommandBridge；请核对声明，原插件不会被替换。")
    if type(data["java_major"]) is not int or data["java_major"] not in {8, 11, 16, 17, 21, 25}:
        raise ArchiveInstallError("启动配置的 Java 版本不受支持。")
    if not isinstance(data["minecraft_version"], str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", data["minecraft_version"]):
        raise ArchiveInstallError("Minecraft 版本格式无效。")
    classpath = _argument_list(data["classpath"], "Classpath")
    if data["core_jar"] not in classpath or len(set(classpath)) != len(classpath):
        raise ArchiveInstallError("Classpath 必须包含唯一的服务端核心。")
    for value in classpath:
        library = _relative_file(root, value, "Classpath 文件")
        if library.suffix.lower() != ".jar":
            raise ArchiveInstallError("Classpath 只接受包内 JAR 文件。")
    _validate_classpath_main(root, classpath, data["core_jar"], actual_main)
    jvm = _argument_list(data["jvm_args"], "JVM 参数")
    if any(not arg.startswith(("-Xms", "-Xmx", "-XX:", "-D")) or arg.startswith("-Dqizhang.panel.server_id=") for arg in jvm):
        raise ArchiveInstallError("启动配置 JVM 参数只接受内存、-XX 和 -D 设置。")
    _argument_list(data["game_args"], "游戏参数")
    # The classpath contract remains useful when its preferred runtime was not
    # included. Runtime selection below tries compatible bundled/local Java.
    _bundled_java_location(root, data["java_path"])
    if generated:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _write_manifest_launcher(root, spec, server_id):
    # Run only generated code at the user's later start request. Import never
    # executes the archive's scripts, main class, or bundled Java executable.
    runtime = {**spec, "server_id": server_id}
    (root / "qizhang-import-launch.json").write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
    script = r'''$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'qizhang-import-launch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$java = [string]$cfg.java_path
if (-not [System.IO.Path]::IsPathRooted($java)) { $java = Join-Path $PSScriptRoot $java }
if (-not (Test-Path -LiteralPath $java -PathType Leaf)) { throw 'Selected Java is missing. Restore the runtime or choose a compatible Java in server settings.' }
$jvm = @($cfg.jvm_args | Where-Object { $_ -notmatch '^-Xm[sx]' })
foreach ($line in (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'user_jvm_args.txt') -Encoding UTF8)) {
    $line = $line.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    foreach ($token in [regex]::Matches($line, '(?:[^\s"]+|"[^"]*")+')) {
        $arg = $token.Value.Replace('"', '')
        if ($arg -notmatch '^-(Xms|Xmx|XX:|D)' -or $arg.StartsWith('-Dqizhang.panel.server_id=')) { throw 'Unsupported user_jvm_args option.' }
        $jvm += $arg
    }
}
$javaArgs = @($jvm) + @(('-Dqizhang.panel.server_id=' + $cfg.server_id), '-cp', ($cfg.classpath -join ';'), $cfg.main_class) + @($cfg.game_args) + @($args)
& $java @javaArgs
exit $LASTEXITCODE
'''
    (root / "qizhang-imported-start.ps1").write_text(script, encoding="utf-8-sig")
    launcher = "qizhang-imported-start.bat"
    (root / launcher).write_text('@echo off\r\nsetlocal DisableDelayedExpansion\r\ncd /d "%~dp0"\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qizhang-imported-start.ps1" %*\r\nexit /b %errorlevel%\r\n', encoding="utf-8")
    return launcher


def _write_java8_launcher(root, payload, server_id, game_args=None, literal_source=None):
    """Java 8 lacks @argument-file support; expand the panel's JVM file ourselves."""
    data = {"core_jar": payload, "server_id": server_id, "game_args": ["nogui"] if game_args is None else list(game_args)}
    if literal_source:
        data["literal_script_source"] = literal_source
    (root / "qizhang-import-launch.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    script = r'''$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'qizhang-import-launch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$java = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'qizhang-java-path.txt') -Raw -Encoding UTF8).Trim()
if (-not [System.IO.Path]::IsPathRooted($java)) { $java = Join-Path $PSScriptRoot $java }
if (-not (Test-Path -LiteralPath $java -PathType Leaf)) { throw 'Selected Java is missing. Choose a compatible Java in server settings.' }
$jvm = @()
foreach ($line in (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'user_jvm_args.txt') -Encoding UTF8)) {
    $line = $line.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    foreach ($token in [regex]::Matches($line, '(?:[^\s"]+|"[^"]*")+')) {
        $arg = $token.Value.Replace('"', '')
        if ($arg -notmatch '^-(Xms|Xmx|XX:|D)' -or $arg.StartsWith('-Dqizhang.panel.server_id=')) { throw 'Unsupported user_jvm_args option.' }
        $jvm += $arg
    }
}
$javaArgs = @($jvm) + @(('-Dqizhang.panel.server_id=' + $cfg.server_id), '-jar', $cfg.core_jar) + @($cfg.game_args) + @($args)
& $java @javaArgs
exit $LASTEXITCODE
'''
    (root / "qizhang-imported-start.ps1").write_text(script, encoding="utf-8-sig")
    launcher = "qizhang-imported-start.bat"
    (root / launcher).write_text('@echo off\r\nsetlocal DisableDelayedExpansion\r\ncd /d "%~dp0"\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qizhang-imported-start.ps1" %*\r\nexit /b %errorlevel%\r\n', encoding="utf-8")
    return launcher



def core_java_requirement(root, core, minecraft_version):
    """Combine game requirements with the actual entry class bytecode floor.

    A wrapper class alone is not evidence of the requirements of every loaded
    dependency. Unknown game versions remain unknown; proxy/Nukkit have no
    one-to-one Java-edition game version and use their own entry requirement.
    """
    from native_server_install import java_requirement
    from native_platform_templates import template
    runtime_rule = template(core[0])
    requirement = java_requirement(minecraft_version)
    major = requirement["major"] if requirement["known"] else None
    class_floor = None
    if core[1] == "jar":
        try:
            jar = Path(root) / core[2]
            main = jar_manifest(jar).get("Main-Class", "").strip()
            with zipfile.ZipFile(jar) as package:
                with package.open(main.replace(".", "/") + ".class") as stream:
                    header = stream.read(8)
                # Bootstrap may target an older Java than the proxy it loads.
                # Inspect owned classes, not optional/Multi-Release vendor code.
                if runtime_rule["runtime_policy"] == "entry-bytecode-minimum":
                    prefix = runtime_rule["class_prefix"]
                    for member in package.infolist():
                        if member.filename.startswith(prefix) and member.filename.endswith(".class"):
                            with package.open(member) as stream:
                                other = stream.read(8)
                            if other[:4] == b"\xca\xfe\xba\xbe" and len(other) == 8 and other[6:8] > header[6:8]:
                                header = other
            if len(header) == 8 and header[:4] == b"\xca\xfe\xba\xbe":
                class_floor = max(8, int.from_bytes(header[6:8], "big") - 44)
        except (OSError, KeyError, zipfile.BadZipFile):
            pass
    if runtime_rule["runtime_policy"] == "entry-bytecode-minimum":
        major = class_floor
    elif major is not None and class_floor:
        major = max(major, class_floor)
    return {"major": major, "bits": 64, "known": major is not None,
            "label": "64 位 Java " + str(major) if major is not None else "请指定核心兼容的 64 位 Java",
            "class_minimum": class_floor}


def _finish_native_import(source, destination, server, core, adapt, progress):
    from native_platform_launch import write
    from native_platform_templates import receipt as template_receipt
    if not adapt:
        raise ArchiveInstallError("基岩原生端和 PocketMine 需要勾选生成专用启动文件，以便面板可靠发送命令和正常停服；原启动文件仍会保留。")
    platform, kind, entry, loader = core
    server_id = "server-" + uuid.uuid4().hex[:8]
    scripts = sorted([*server.glob("*.bat"), *server.glob("*.cmd")])
    originals = [p for p in scripts if not p.name.lower().startswith("qizhang-")]
    runtime_path = ""
    if kind == "php":
        # No arbitrary archive program runs during import. Preserve the complete
        # vendor runtime tree. PM requires its matched extensions, not stock PHP.
        candidates = [p for p in server.rglob("php.exe")
                      if len(p.relative_to(server).parts) <= 7]
        if len(candidates) != 1:
            raise ArchiveInstallError("PocketMine 需要对应版本的完整 PHP 运行组件。包内未找到唯一 php.exe；请补齐官方 Windows 运行时后再导入。")
        runtime_path = candidates[0].relative_to(server).as_posix()
    if adapt:
        launch = write(server, platform, entry, runtime_path=runtime_path,
                       runtime_args=[], server_args=[], server_id=server_id)
        launcher = launch["launch_script"]
        generated = [launcher, "qizhang-platform-launch.json"]
    else:
        if len(originals) != 1:
            raise ArchiveInstallError("沿用原启动文件需要包内存在唯一 BAT/CMD；也可勾选生成七章专用启动文件。")
        launcher, generated = originals[0].name, []
    adaptation = {"enabled": adapt, "requested": adapt, "generated": generated,
                  "original_scripts": [p.name for p in originals],
                  "message": "已绑定原生运行时；原启动文件保留。"}
    metadata = {"source_archive": source.name, "platform": platform, "java_major": None,
                "core_selection": _selection_record(server, core),
                "launch_script": launcher, "startup_adaptation": adaptation,
                "runtime_validation": "static-only; execution occurs only after Start",
                "platform_template": template_receipt(platform)}
    (server / "qizhang-import.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    progress(95, "保存原生服务端与启动配置…")
    checked_destination(destination)
    if destination.exists():
        destination.rmdir()
    server.rename(destination)
    progress(100, "已导入，尚未启动。此平台无需 Java。")
    return {"id": server_id, "name": destination.name[:40], "path": str(destination),
            "platform": platform, "minecraft_version": "", "loader_version": loader,
            "java_major": None, "java_selection": {"message": "此平台无需 Java。"},
            "launch_script": launcher, "supports_watchdog": False, "voice_port": 24454,
            "startup_adaptation": adaptation, "platform_template": template_receipt(platform)}


def _extract_archive(source, stage, on_progress):
    """Bounded safe extraction shared by preview and install; never executes ZIP code."""
    on_progress(2, "检查压缩包目录和服务端文件…")
    with zipfile.ZipFile(source) as package:
        entries = package.infolist()
        if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_EXPANDED:
            raise ArchiveInstallError("压缩包超过 150000 个文件或 40 GB 展开限制。")
        check_uninstalled_modpack(package)
        total = sum(item.file_size for item in entries)
        if shutil.disk_usage(stage).free < total + 256 * 1024**2:
            raise ArchiveInstallError("目标磁盘空间不足，请至少额外保留 256 MB。")
        known = set()
        expanded = 0
        for index, item in enumerate(entries):
            parts = safe_name(item.filename)
            key = "/".join(parts).casefold()
            mode = item.external_attr >> 16
            if key in known or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}) or item.external_attr & 0x400:
                raise ArchiveInstallError("压缩包包含重复路径、链接或不支持的文件类型。")
            known.add(key)
            target = stage.joinpath(*parts)
            if not target.resolve().is_relative_to(stage.resolve()):
                raise ArchiveInstallError("压缩包路径越界，已停止安装。")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(item) as reader, target.open("xb") as writer:
                copied = 0
                while chunk := reader.read(1024 * 1024):
                    copied += len(chunk)
                    expanded += len(chunk)
                    if copied > item.file_size or expanded > MAX_EXPANDED:
                        raise ArchiveInstallError("压缩包展开大小异常。")
                    writer.write(chunk)
            if index % 100 == 0:
                on_progress(5 + int(75 * expanded / max(total, 1)), "正在解压服务器文件…")


def install_archive(archive, server_dir, java_path, on_progress, cache_root=None, selected_core=None, adapt_startup=True, official_descriptor=None, _preview_stage=None):
    from native_server_install import discover_java, inspect_java, java_requirement
    from native_import_adapter import plan, bootstrap_plan, write, split_selection
    from native_platform_templates import receipt as template_receipt
    if type(adapt_startup) is not bool:
        raise ArchiveInstallError("启动适配选项必须为勾选或未勾选。")
    source = Path(archive).resolve()
    if source.suffix.lower() != ".zip" or not source.is_file():
        raise ArchiveInstallError("请选择服务器 ZIP 压缩包。")
    destination = checked_destination(server_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = (Path(_preview_stage) if _preview_stage is not None else
             destination.parent / (".qizhang-server-import-" + uuid.uuid4().hex))
    if stage.parent.resolve() != destination.parent.resolve() or not stage.name.startswith(".qizhang-server-import-"):
        raise ArchiveInstallError("导入暂存目录不属于当前目标目录。")
    if _preview_stage is None:
        stage.mkdir()
    try:
        if _preview_stage is None:
            _extract_archive(source, stage, on_progress)
        on_progress(83, "识别服务端核心和启动配置…")
        prepared = None
        try:
            server, core = find_server_root(stage, selected_core=split_selection(selected_core)[0])
        except ArchiveSelectionRequired:
            raise
        except ArchiveInstallError:
            from native_archive_bootstrap import prepare
            prepared = prepare(stage, java_path, on_progress, cache_root=cache_root,
                               adapt_startup=adapt_startup)
            if prepared is None:
                raise
            server, core = prepared["server_root"], prepared["core"]
        platform, kind, payload, loader_version = core
        if kind in {"native", "php"}:
            return _finish_native_import(source, destination, server, core, adapt_startup, on_progress)
        if official_descriptor:
            # Only an internal, hash-verified official provider supplies this contract.
            platform = official_descriptor["platform"]
            core = (platform, kind, payload, str(official_descriptor.get("loader_version", "")))
            loader_version = core[3]
        launch_spec = load_launch_manifest(server, core)
        import_plan = (bootstrap_plan(prepared) if prepared else
                       plan(server, core, stage, selected_core, adapt_startup, launch_spec))
        profile = import_plan["profile"]
        literal_launch = ({"jvm_args": profile["jvm_args"], "game_args": profile["game_args"],
                           "source": profile["source"]["path"]} if profile else None)
        minecraft_version, evidence = detect_minecraft_version(server, core)
        if prepared:
            if minecraft_version and minecraft_version != prepared["minecraft_version"]:
                raise ArchiveInstallError("官方安装后的 Minecraft 版本与原服务端启动配置不一致。")
            minecraft_version = prepared["minecraft_version"]
            evidence.append({"source": "verified-bootstrap-template", "version": minecraft_version})
        if launch_spec:
            if minecraft_version and _version_key(minecraft_version) != _version_key(launch_spec["minecraft_version"]):
                raise ArchiveInstallError("启动配置的 Minecraft 版本与服务端核心不一致。")
            minecraft_version = launch_spec["minecraft_version"]
            evidence.append({"source": LAUNCH_MANIFEST, "version": minecraft_version})
        if official_descriptor:
            stated = official_descriptor.get("minecraft_version", "")
            if minecraft_version and stated and minecraft_version != stated:
                raise ArchiveInstallError("官方下载内容与选择的 Minecraft 版本不一致。")
            minecraft_version = stated or minecraft_version
        requirement = core_java_requirement(server, core, minecraft_version)
        if official_descriptor and official_descriptor.get("java_major"):
            requirement = {"major": official_descriptor["java_major"], "bits": 64, "known": True,
                           "label": "64 位 Java " + str(official_descriptor["java_major"])}
        server_id = "server-" + uuid.uuid4().hex[:8]
        if launch_spec:
            if requirement["known"] and launch_spec["java_major"] != requirement["major"]:
                raise ArchiveInstallError("随包启动配置需要与 Minecraft " + minecraft_version + " 匹配的 " + requirement["label"] + "。")
        required_major = requirement["major"] if requirement["known"] else (launch_spec["java_major"] if launch_spec else None)
        if required_major is None and not java_path:
            raise ArchiveInstallError("已识别服务端核心，但无法确定 Minecraft 版本。请手动选择该服务器兼容的 64 位 Java；不会默认要求 Java 21。")
        on_progress(86, "正在检查包内 Java；将优先使用与服务器版本匹配的 Windows 64 位运行时…")
        preferred_java = (launch_spec["java_path"] if launch_spec else
                          profile["java_hint"] if profile and profile.get("java_hint_kind") == "bundled" else "")
        from native_platform_templates import template
        minimum_java = template(platform)["runtime_policy"] == "entry-bytecode-minimum"
        selection = discover_bundled_java(server, required_major, preferred_java, minimum=minimum_java)
        bundled = selection["candidates"][0] if selection["candidates"] else None
        if bundled is None and server != stage and required_major is not None:
            outer = discover_bundled_java(stage, required_major, minimum=minimum_java)
            selection["outer_archive_scan"] = outer
            for candidate in outer["candidates"]:
                if stage.joinpath(*safe_name(candidate["path"])).resolve().is_relative_to(server.resolve()):
                    continue
                try:
                    bundled = copy_outer_bundled_java(stage, server, candidate)
                    selection["candidates"].append(bundled)
                    break
                except ArchiveInstallError as error:
                    if len(outer["rejected"]) < MAX_JAVA_REPORT_ITEMS:
                        outer["rejected"].append({"path": candidate["path"], "reason": str(error)})
        java_relative = ""
        if bundled:
            java_relative = bundled["path"]
            java = str(destination.joinpath(*safe_name(java_relative)))
            java_major = bundled["major"]
            java_source = "bundled"
            java_validation = "bundled-release-static-only"
            selection["message"] = f"已选择包内 Java {java_major}（64 位）：{java_relative}。"
            if bundled.get("copied_from_archive"):
                selection["message"] += " 来源：" + bundled["copied_from_archive"] + "；已将完整运行时复制到本服务器目录。"
        else:
            on_progress(87, ("Minecraft " + minecraft_version + "：" if minecraft_version else "Minecraft 版本未知：") + requirement["label"])
            candidates = ([prepared["java_path"]] if prepared else discover_java(None if minimum_java else required_major)) if not java_path else []
            if minimum_java and candidates:
                infos = [inspect_java(p) for p in candidates]
                candidates = [i["path"] for i in sorted(infos, key=lambda item: item["major"]) if required_major is None or i["major"] >= required_major]
            if profile and profile.get("java_hint_kind") == "absolute" and not java_path:
                matched = [item for item in candidates if os.path.normcase(str(item)) == os.path.normcase(profile["java_hint"])]
                if matched:
                    candidates = matched + [item for item in candidates if item not in matched]
            info = inspect_java(java_path or (candidates[0] if candidates else ""), None if minimum_java else required_major)
            java, java_major = info["path"], info["major"]
            if required_major is not None and (java_major < required_major if minimum_java else java_major != required_major):
                raise ArchiveInstallError(f"此服务器需要 64 位 Java {required_major}，选择的 Java {java_major} 不匹配。")
            java_source = "local-manual" if java_path else "local-auto"
            java_validation = "external-java-version"
            selection["message"] = f"包内没有兼容的 Java；已{'使用手动选择的' if java_path else '自动选择本机'} Java {java_major}（64 位）。"
        selection.update(source=java_source, selected_path=java_relative or java, selected_major=java_major)
        on_progress(90, selection["message"])
        if kind == "args" and java_major == 8:
            raise ArchiveInstallError("这个核心使用 Java 参数文件启动，不能使用 Java 8；请核对服务端版本。")
        if any(c in java for c in '%!\r\n"&|<>^'):
            raise ArchiveInstallError("Java 路径含有批处理不支持的字符，请选择普通安装路径。")
        if any(c in payload for c in '%!\r\n"&|<>^'):
            raise ArchiveInstallError("核心文件名含有不支持的启动字符。")
        if import_plan["enabled"]:
            on_progress(92, "读取原启动参数，生成七章面板专用启动文件…")
            launcher = write(server, core, import_plan, launch_spec, server_id, minecraft_version,
                             java_relative or java, java_major)
            (server / "qizhang-java-path.txt").write_text((java_relative or java) + "\n", encoding="utf-8")
        else:
            launcher = import_plan["original_launcher"]
            import_plan["generated"] = []
            import_plan["message"] = "已沿用原启动文件：" + launcher + "；裸 java 命令使用面板选定的 Java，原脚本的显式 Java 路径仍优先。"
            selection["message"] = f"已核对兼容 Java {java_major} 可用；原启动文件和系统 Java 设置保持原样。"
        if platform not in {"velocity", "bungeecord", "waterfall"} and not (server / "server.properties").is_file():
            from native_platforms import profile as platform_profile
            defaults = {"server-port": str(platform_profile(platform)["default_port"]), "online-mode": "true", "max-players": "20"}
            if prepared:
                defaults.update(prepared.get("default_properties", {}))
            (server / "server.properties").write_text("".join(str(k) + "=" + str(v) + "\n" for k, v in defaults.items()), encoding="utf-8")
        if platform not in {"velocity", "bungeecord", "waterfall", "nukkit"} and not (server / "eula.txt").is_file():
            (server / "eula.txt").write_text("eula=false\n", encoding="ascii")
        metadata = {"source_archive": source.name, "platform": platform, "loader_version": loader_version,
                    "minecraft_version": minecraft_version, "java_major": java_major,
                    "java_requirement": requirement, "version_evidence": evidence,
                    "java_path": java, "java_relative_path": java_relative, "java_source": java_source,
                    "java_selection": selection, "launch_script": launcher, "existing_eula_preserved": True,
                    "launch_manifest": LAUNCH_MANIFEST if launch_spec else None,
                    "java_validation": java_validation, "core_selection": _selection_record(server, core),
                    "literal_launch": literal_launch, "startup_adaptation": import_plan, "platform_template": template_receipt(platform)}
        if launch_spec:
            metadata["command_channel"] = launch_spec["command_channel"]
        (server / "qizhang-import.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        on_progress(95, "保存服务器目录并绑定启动配置…")
        checked_destination(destination)
        if destination.exists():
            destination.rmdir()
        server.rename(destination)
        on_progress(100, "服务器压缩包已导入，尚未开服。")
        return {"id": server_id, "name": destination.name[:40], "path": str(destination),
                "platform": platform, "minecraft_version": minecraft_version, "loader_version": loader_version,
                "java_major": java_major, "java_requirement": requirement, "version_evidence": evidence,
                "java_source": java_source, "java_relative_path": java_relative, "java_selection": selection,
                "launch_script": launcher, "supports_watchdog": False, "voice_port": 24454,
                "startup_adaptation": import_plan, "platform_template": template_receipt(platform)}
    finally:
        # stage is a fresh UUID-owned directory; ZIP links were rejected above.
        if stage.exists():
            checked = stage.resolve()
            if checked.parent == destination.parent.resolve() and checked.name.startswith(".qizhang-server-import-"):
                shutil.rmtree(checked)


def _archive_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _tree_fingerprint(root):
    """Constant-buffer content seal, including added/removed files and directories."""
    root = Path(root).absolute()
    resolved_root = root.resolve()
    digest = hashlib.sha256()
    count = total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for item in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
            if (item.is_symlink() or getattr(item, 'is_junction', lambda: False)()
                    or not item.resolve().is_relative_to(resolved_root)):
                raise ArchiveInstallError("预览暂存文件含有链接或越界路径，请重新预览。")
        relative = Path(directory).relative_to(root).as_posix()
        digest.update(("D\0" + relative + "\0").encode("utf-8"))
        for name in files:
            path = Path(directory) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ArchiveInstallError("预览暂存文件类型已改变，请重新预览。")
            size = path.stat().st_size
            count += 1
            total += size
            if count > MAX_FILES or total > MAX_EXPANDED:
                raise ArchiveInstallError("预览暂存文件超过导入限制。")
            digest.update(("F\0" + path.relative_to(root).as_posix() + "\0" + str(size) + "\0").encode("utf-8"))
            digest.update(bytes.fromhex(_archive_sha(path)))
    return {"sha256": digest.hexdigest(), "files": count, "bytes": total}


def _preview_launch(server, core, import_plan, manifest):
    from native_import_adapter import _effective_jvm
    from native_launch_settings import _jvm_file
    from native_platforms import profile as platform_profile
    spec = platform_profile(core[0], server)
    if not import_plan["enabled"]:
        return dict(kind="original-script", entry=import_plan["original_launcher"], jvm_args=[], server_args=[],
                    classpath=[], main_class="", launcher=import_plan["original_launcher"],
                    source=import_plan.get("source"), adaptation=False, command_channel="original-script-capture")
    selected = import_plan.get("profile")
    kind, entry, cp, main = core[1], core[2], [], ""
    if manifest:
        kind, cp, main = "classpath", list(manifest["classpath"]), manifest["main_class"]
        jvm = list(manifest["jvm_args"])
        if (server / "user_jvm_args.txt").is_file():
            jvm += _jvm_file(server)
        game = list(manifest["game_args"])
    elif selected:
        kind, entry = selected["kind"], selected["entry"]
        cp, main = selected.get("classpath", []), selected.get("main_class", "")
        jvm, game = list(selected["jvm_args"]), list(selected["game_args"])
    else:
        jvm = _jvm_file(server)
        game = [] if spec["family"] == "proxy" or core[0] == "nukkit" else ["nogui"]
    return dict(kind=kind, entry=entry, jvm_args=_effective_jvm(jvm), server_args=game, classpath=cp,
                main_class=main, launcher="qizhang-managed-start.bat", source=import_plan.get("source"),
                adaptation=True, command_channel="owned-stdin")


def _preview_runtime(server, stage, core, version, manifest, import_plan, java_path):
    from native_platforms import profile as platform_profile
    spec = platform_profile(core[0], server)
    if spec["runtime"] != "java":
        candidates = ([core[2]] if core[1] == "native" else
                      [p.relative_to(server).as_posix() for p in server.rglob("php.exe")
                       if len(p.relative_to(server).parts) <= 7])
        return dict(kind=spec["runtime"], requirement={"known": bool(candidates), "major": None, "bits": 64,
                    "label": "无需 Java；使用基岩原生运行程序" if core[1] == "native" else "使用随包完整 PocketMine PHP 运行时"},
                    source="bundled", selected_path=candidates[0] if len(candidates) == 1 else "",
                    validation="static-only", reason="保留随包运行时；安装不执行包内程序。",
                    bundled_candidates=candidates, rejected=[])
    requirement = core_java_requirement(server, core, version)
    required = requirement["major"] if requirement["known"] else (manifest["java_major"] if manifest else None)
    if manifest and requirement["known"] and manifest["java_major"] != required:
        raise ArchiveInstallError("启动清单中的 Java 与核心所需版本不一致。")
    selected = import_plan.get("profile")
    preferred = (manifest["java_path"] if manifest else
                 selected["java_hint"] if selected and selected.get("java_hint_kind") == "bundled" else "")
    minimum = spec["runtime_policy"] == "entry-bytecode-minimum"
    report = discover_bundled_java(server, required, preferred, minimum=minimum)
    bundled = report["candidates"][0] if report["candidates"] else None
    source = "bundled" if bundled else "local-manual" if java_path else "local-auto-pending"
    path = bundled["path"] if bundled else str(java_path or "")
    reason = ("随包 release 声明与核心要求匹配；优先使用随包 Java。" if bundled else
              "安装时执行本机 Java -version 验证所选版本，不执行包内 Java。" if java_path else
              "包内未找到兼容运行时；安装时自动查找并验证本机对应 Java。")
    outer_candidates = []
    if bundled is None and stage != server and required is not None:
        outer = discover_bundled_java(stage, required, minimum=minimum)
        outer_candidates = [item for item in outer["candidates"]
                            if not (stage / item["path"]).resolve().is_relative_to(server.resolve())]
        if outer_candidates:
            source, path = "bundled-outer-pending", outer_candidates[0]["path"]
            reason = "外层压缩包有兼容 Java；安装时校验完整运行库后复制，缺失时转本机 Java。"
    return dict(kind="java", requirement=dict(requirement, minimum=minimum), source=source, selected_path=path,
                validation="bundled-release-static-only" if bundled else "pending-install-validation",
                reason=reason, bundled_candidates=report["candidates"], rejected=report["rejected"],
                outer_candidates=outer_candidates)


def preview_extracted_archive(stage, java_path="", selected_core=None, adapt_startup=True):
    """Use the same detectors, argument parser and runtime policy as final import."""
    from native_import_adapter import plan, split_selection
    from native_platforms import profile as platform_profile
    from native_platform_templates import receipt as template_receipt
    stage = Path(stage)
    result = dict(schema_version=1, can_install=False, selection_required=False, candidates=[], selected=None,
                  minecraft_version="", loader_version="", version_evidence=[], runtime={}, launch={}, template={},
                  capabilities={}, uncertainties=[], summary="", bootstrap=None)
    try:
        server, core = find_server_root(stage, split_selection(selected_core)[0])
    except ArchiveSelectionRequired as error:
        result.update(selection_required=True, candidates=error.choices, summary=str(error))
        return result
    except ArchiveInstallError as original:
        from native_archive_bootstrap import detect, BootstrapError
        try:
            bootstrap = detect(stage)
        except BootstrapError as error:
            result.update(summary=str(error), uncertainties=[str(error)])
            return result
        if not bootstrap:
            result.update(summary=str(original), uncertainties=[str(original)])
            return result
        platform = bootstrap["platform"]
        spec = platform_profile(platform)
        result.update(can_install=bool(adapt_startup), minecraft_version=bootstrap["minecraft_version"],
                      loader_version=bootstrap["loader_version"], template=template_receipt(platform),
                      capabilities=spec["capabilities"],
                      version_evidence=[{"source": bootstrap["source"]["path"], "version": bootstrap["minecraft_version"]}],
                      selected={"platform": platform, "server_path": bootstrap["server_root"].relative_to(stage).as_posix(),
                                "kind": "official-bootstrap", "entry": bootstrap["source"]["path"]},
                      runtime={"kind": "java", "requirement": {"major": bootstrap["java_major"], "known": True,
                               "bits": 64, "label": "64 位 Java " + str(bootstrap["java_major"])},
                               "source": "local-manual" if java_path else "local-auto-pending", "selected_path": str(java_path or ""),
                               "reason": "安装时使用对应本机 Java 完成官方初始化，预览未执行安装器。",
                               "validation": "pending-install-validation", "bundled_candidates": [], "rejected": []},
                      launch={"kind": "official-bootstrap", "entry": "libraries/net/minecraftforge/forge/" + bootstrap["minecraft_version"] + "-" + bootstrap["loader_version"] + "/win_args.txt",
                              "jvm_args": bootstrap.get("jvm_args") or [], "server_args": bootstrap["game_args"],
                              "classpath": [], "main_class": "", "launcher": "qizhang-managed-start.bat", "source": bootstrap["source"],
                              "adaptation": True, "command_channel": "owned-stdin"},
                      bootstrap={"template": bootstrap["template"], "requires_download": True},
                      uncertainties=["尚未生成核心；确认导入后从官方源下载并校验安装文件。"],
                      summary="识别为官方初始化模板；预览只读取文件，确认导入后补全服务端。")
        result["launch"]["arguments_pending"] = bootstrap.get("jvm_args") is None
        if result["launch"]["arguments_pending"]:
            result["uncertainties"].append("JVM 参数文件尚未生成；安装后采用并记录官方安装器生成的参数。")
        if not adapt_startup:
            result["uncertainties"].append("此初始化包需要勾选生成七章专用启动文件。")
        return result
    choice = _choice(server, core, server.relative_to(stage).as_posix())
    spec = platform_profile(core[0], server)
    result.update(selected=choice, candidates=[choice], template=template_receipt(core[0]),
                  capabilities=spec["capabilities"], loader_version=core[3])
    try:
        if core[1] in {"native", "php"}:
            runtime = _preview_runtime(server, stage, core, "", None, {}, java_path)
            result.update(runtime=runtime, can_install=bool(adapt_startup and runtime["selected_path"]),
                          launch={"kind": core[1], "entry": core[2], "launcher": "qizhang-platform-start.bat",
                                  "jvm_args": [], "server_args": [], "classpath": [], "main_class": "", "source": None,
                                  "adaptation": True, "command_channel": "owned-stdin"})
            if not adapt_startup:
                result["uncertainties"].append("此平台需要勾选生成专用启动文件。")
            if not runtime["selected_path"]:
                result["uncertainties"].append("未找到唯一且完整的对应 PHP 运行组件，请补齐后重试。")
        else:
            manifest = load_launch_manifest(server, core)
            import_plan = plan(server, core, stage, selected_core, adapt_startup, manifest)
            version, evidence = detect_minecraft_version(server, core)
            if manifest:
                if version and _version_key(version) != _version_key(manifest["minecraft_version"]):
                    raise ArchiveInstallError("启动配置的 Minecraft 版本与服务端核心不一致。")
                version = manifest["minecraft_version"]
                evidence.append({"source": LAUNCH_MANIFEST, "version": version})
            result.update(minecraft_version=version, version_evidence=evidence,
                          launch=_preview_launch(server, core, import_plan, manifest),
                          runtime=_preview_runtime(server, stage, core, version, manifest, import_plan, java_path))
            requirement = result["runtime"]["requirement"]
            result["can_install"] = bool(requirement["known"] or java_path)
            if not requirement["known"]:
                result["uncertainties"].append("无法确定所需 Java 版本；请手动选择兼容 Java，面板不会默认要求 Java 21。")
            if not version and spec["family"] == "java":
                result["uncertainties"].append("Minecraft 版本尚不能确认；保留未知状态。")
            if not import_plan["enabled"]:
                result["uncertainties"].append("将使用原启动文件；脚本的动态行为与显式 Java 路径仍由原脚本决定。")
            if result["runtime"]["source"] != "bundled":
                result["uncertainties"].append("本机运行时可用性在确认安装时验证；尚未启动服务器。")
        result["launch"]["stop_command"] = spec["stop_command"]
        result["launch"]["ready_pattern"] = spec["ready_pattern"]
        result["summary"] = spec["label"] + (" " + result["minecraft_version"] if result["minecraft_version"] else "") + "；" + result["runtime"].get("reason", "")
    except ArchiveSelectionRequired as error:
        result.update(can_install=False, selection_required=True, candidates=error.choices, summary=str(error))
    except (ArchiveInstallError, OSError, ValueError) as error:
        result.update(can_install=False, summary=str(error), uncertainties=[str(error)])
    return result


class ArchivePreviewSession:
    """One bounded, owner-scoped disk preview. Host must scope this to an account.

    Tokens are single-use and bind archive bytes, extracted bytes, all options and
    rule revision. Re-selecting a core reuses extraction. No idle worker or timer.
    """
    def __init__(self, cache_root):
        import threading
        self.cache_root = Path(cache_root).resolve() / "archive-previews"
        self._lock = threading.RLock()
        self._record = None

    @staticmethod
    def _remove_owned(stage):
        stage = Path(stage).absolute()
        if not stage.name.startswith(".qizhang-server-import-") or stage.is_symlink() or getattr(stage, "is_junction", lambda: False)():
            raise ArchiveInstallError("暂存目录的安全边界发生变化，未清理未知目录。")
        from native_server_install import _check_reparse
        _check_reparse(stage)
        if stage.exists():
            # This exact directory was allocated by this session, never caller supplied.
            shutil.rmtree(stage)

    def close(self):
        with self._lock:
            if self._record:
                self._remove_owned(self._record["stage"])
                self._record = None

    @staticmethod
    def _options(archive, java_path, selected_core, adapt_startup, server_dir):
        if type(adapt_startup) is not bool:
            raise ArchiveInstallError("启动适配选项必须为勾选或未勾选。")
        if selected_core is not None and not isinstance(selected_core, str):
            raise ArchiveInstallError("启动目标选择格式无效。")
        return {"archive": str(Path(archive).resolve()), "java_path": str(java_path or ""),
                "selected_core": selected_core, "adapt_startup": adapt_startup,
                "server_dir": str(Path(server_dir).resolve()) if server_dir else ""}

    def prepare(self, archive, java_path="", selected_core=None, adapt_startup=True, on_progress=None, server_dir=""):
        import time
        from copy import deepcopy
        from native_server_install import _check_reparse
        from native_platform_templates import RULE_VERSION
        progress = on_progress or (lambda *args: None)
        options = self._options(archive, java_path, selected_core, adapt_startup, server_dir)
        source = Path(options["archive"])
        _check_reparse(source)
        if source.suffix.lower() != ".zip" or not source.is_file():
            raise ArchiveInstallError("请选择服务器 ZIP 压缩包。")
        destination = checked_destination(server_dir) if server_dir else None
        with self._lock:
            progress(1, "正在校验压缩包指纹…")
            source_hash = _archive_sha(source)
            if self._record and (self._record["options"]["archive"] != str(source)
                                 or self._record["archive_sha256"] != source_hash
                                 or time.monotonic() - self._record["created"] > 1800):
                self.close()
            if not self._record:
                parent = destination.parent if destination else self.cache_root
                parent.mkdir(parents=True, exist_ok=True)
                _check_reparse(parent)
                stage = parent / (".qizhang-server-import-" + uuid.uuid4().hex)
                stage.mkdir()
                try:
                    _extract_archive(source, stage, progress)
                    if _archive_sha(source) != source_hash:
                        raise ArchiveInstallError("压缩包在预览过程中已变化，请重新预览。")
                except BaseException:
                    self._remove_owned(stage)
                    raise
                self._record = {"stage": stage, "archive_sha256": source_hash, "options": options,
                                "created": time.monotonic(), "seal": None}
            record = self._record
            record.pop("token", None)
            if record["seal"] is not None and _tree_fingerprint(record["stage"]) != record["seal"]:
                self.close()
                raise ArchiveInstallError("预览暂存文件已变化，请重新预览。")
            progress(84, "正在读取核心、原启动文件和运行时要求…")
            result = preview_extracted_archive(record["stage"], java_path, selected_core, adapt_startup)
            record.update(options=options, token=uuid.uuid4().hex, result=result,
                          seal=_tree_fingerprint(record["stage"]), rule_version=RULE_VERSION)
            result.update(preview_token=record["token"], archive={"name": source.name, "sha256": source_hash,
                          "bytes": source.stat().st_size})
            progress(100, "识别预览完成；确认后才安装并绑定服务器。")
            return deepcopy(result)

    def install(self, preview_token, archive, server_dir, java_path, on_progress,
                selected_core=None, adapt_startup=True, cache_root=None):
        import time
        from native_platform_templates import RULE_VERSION
        from native_server_install import _check_reparse
        with self._lock:
            record = self._record
            if not record or not isinstance(preview_token, str) or record.get("token") != preview_token:
                raise ArchiveInstallError("导入预览已失效，请重新预览后确认安装。")
            options = self._options(archive, java_path, selected_core, adapt_startup, server_dir)
            expected = dict(record["options"])
            # Callers which did not supply a destination during preview may select it now.
            if not expected["server_dir"]:
                expected["server_dir"] = options["server_dir"]
            if options != expected or record["rule_version"] != RULE_VERSION or time.monotonic() - record["created"] > 1800:
                raise ArchiveInstallError("压缩包、目标目录、Java、启动项或适配选项已改变，请重新预览。")
            if not record["result"]["can_install"] or record["result"]["selection_required"]:
                raise ArchiveInstallError(record["result"]["summary"] or "请先解决预览中的待确认项目。")
            from native_platform_templates import receipt as template_receipt
            if record["result"]["template"] != template_receipt(record["result"]["selected"]["platform"]):
                raise ArchiveInstallError("平台适配规则已改变，请重新预览。")
            destination = checked_destination(server_dir)
            _check_reparse(Path(archive))
            on_progress(1, "正在核对预览与安装文件是否一致…")
            if _archive_sha(archive) != record["archive_sha256"] or _tree_fingerprint(record["stage"]) != record["seal"]:
                self.close()
                raise ArchiveInstallError("压缩包或预览暂存文件已变化，未安装；请重新预览。")
            stage = record["stage"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if stage.parent.resolve() != destination.parent.resolve():
                target = destination.parent / (".qizhang-server-import-" + uuid.uuid4().hex)
                _check_reparse(destination.parent)
                if stage.drive.casefold() == target.drive.casefold():
                    stage.rename(target)
                else:
                    if shutil.disk_usage(destination.parent).free < record["seal"]["bytes"] + 256 * 1024**2:
                        raise ArchiveInstallError("目标磁盘空间不足。")
                    try:
                        shutil.copytree(stage, target)
                        if _tree_fingerprint(target) != record["seal"]:
                            raise ArchiveInstallError("跨盘复制校验失败，原预览保留。")
                    except BaseException:
                        self._remove_owned(target)
                        raise
                    self._remove_owned(stage)
                stage = target
            self._record = None  # One-use token even when Java validation/install fails.
            try:
                result = install_archive(archive, server_dir, java_path, on_progress,
                                         cache_root=cache_root, selected_core=selected_core,
                                         adapt_startup=adapt_startup, _preview_stage=stage)
                result["import_preview"] = {"archive_sha256": record["archive_sha256"],
                                            "staged_sha256": record["seal"]["sha256"],
                                            "template": record["result"]["template"], "verified": True}
                from server_manager import atomic_write_json
                metadata_path = destination / "qizhang-import.json"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["import_preview"] = result["import_preview"]
                atomic_write_json(metadata_path, metadata)
                return result
            finally:
                self._remove_owned(stage)
