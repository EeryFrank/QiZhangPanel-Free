# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Direct, headless launch only from a complete static original launch contract.

Original scripts and manifests remain unchanged. Unknown script steps retain
the original-launch fallback; no archive script or GUI is executed here.
Java validation is deferred until the caller has requested a real start.
"""
import hashlib
import os
from pathlib import Path
import re


MINECRAFT_JAVA_PLATFORMS = frozenset({
    "vanilla", "fabric", "quilt", "forge", "neoforge", "bukkit", "spigot",
    "paper", "purpur", "folia", "sponge", "arclight", "catserver", "mohist", "magma",
})


def headless_args(platform, arguments):
    """Return a copy; do not pass Java-edition options to proxies/Bedrock/PHP."""
    result = list(arguments)
    if platform in MINECRAFT_JAVA_PLATFORMS and not any(
            value in {"nogui", "--nogui"} for value in result):
        result.append("nogui")
    return result


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_original_launch(manager):
    """Return (argv, environment), or None when the original cannot be modeled.

An explicit validated classpath manifest may describe a separate GUI launcher.
Otherwise only the currently selected BAT/CMD's one static Java call is used.
Selecting a Java runtime never selects a different core or invents heap limits.
"""
    from native_server_archive import (LAUNCH_MANIFEST, detect_core,
        detect_minecraft_version, load_launch_manifest, core_java_requirement,
        _bundled_java_location)
    from native_startup_import import (GENERATED, _inside, _read,
        _jvm_argument_file, _check_arguments, parse_startup_script)
    from server_manager import PanelError

    root = Path(manager.server_root).resolve()
    launcher = str(manager.launch_script)
    if (launcher.lower() in GENERATED or Path(launcher).name != launcher
            or Path(launcher).suffix.lower() not in {".bat", ".cmd"}):
        return None
    if str(getattr(manager, "platform", "")) not in MINECRAFT_JAVA_PLATFORMS:
        return None
    identifier = str(manager.server_id)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", identifier):
        raise PanelError("服务器实例标识无效，未运行原启动文件或 Java。")

    # All operations in this section are static reads. In particular, do not
    # call load_launch_manifest without an explicit file: its legacy importer
    # can generate a manifest, which is not a runtime launcher's responsibility.
    try:
        source = _inside(root, launcher)
        watched = {source: _digest(source)}
        core = detect_core(root)
        if core is None or core[0] not in MINECRAFT_JAVA_PLATFORMS:
            return None
        if (root / LAUNCH_MANIFEST).exists():
            manifest_path = _inside(root, LAUNCH_MANIFEST)
            watched[manifest_path] = _digest(manifest_path)
            spec = load_launch_manifest(root, core)
            if spec is None:
                return None
            kind, entry = "classpath", core[2]
            classpath, main = list(spec["classpath"]), spec["main_class"]
            # Repeat path/link checks for every classpath item; full class/main
            # and duplicate-class validation belongs to load_launch_manifest.
            for name in classpath:
                _inside(root, name)
            jvm, game = list(spec["jvm_args"]), list(spec["game_args"])
            if (root / "user_jvm_args.txt").is_file():
                additional, descriptor = _jvm_argument_file(root, "@user_jvm_args.txt")
                jvm.extend(additional)
                watched[_inside(root, descriptor["path"])] = descriptor["sha256"]
            required = spec["java_major"]
            requirement = core_java_requirement(root, core, spec["minecraft_version"])
            version, _ = detect_minecraft_version(root, core)
            if (not requirement.get("known") or required != requirement["major"]
                    or (version and version != spec["minecraft_version"])):
                return None
            preferred = _bundled_java_location(root, spec["java_path"])
            java = preferred if preferred.is_file() else Path(manager.java_path)
        else:
            profile = parse_startup_script(root, launcher, [core])
            watched[source] = profile["source"]["sha256"]
            kind, entry = profile["kind"], profile["entry"]
            classpath, main = list(profile["classpath"]), profile["main_class"]
            jvm, game = list(profile["jvm_args"]), list(profile["game_args"])
            for descriptor in profile["argument_files"]:
                watched[_inside(root, descriptor["path"])] = descriptor["sha256"]
            version, _ = detect_minecraft_version(root, core)
            requirement = core_java_requirement(root, core, version)
            if not requirement.get("known"):
                return None
            required = requirement["major"]
            java = Path(manager.java_path)
            if profile["java_hint_kind"] == "bundled":
                preferred = _inside(root, profile["java_hint"], file=False)
                if preferred.is_file():
                    java = preferred
        if kind == "args":
            _, descriptor = _read(root, entry)
            watched[_inside(root, entry)] = descriptor["sha256"]
        _check_arguments(jvm, game)
        if kind not in {"args", "classpath", "jar"}:
            return None
    except (OSError, ValueError, TypeError, KeyError):
        return None

    # Runtime errors after identifying a complete contract are not permission to
    # retry an unvalidated original script or silently substitute another Java.
    from native_server_install import inspect_java
    from native_import_adapter import _effective_jvm
    from native_launch_settings import _validate_jvm
    if not java.is_absolute():
        try:
            java = _inside(root, str(java))
        except (OSError, ValueError):
            raise PanelError("Java 路径无效或超出服务器目录，未运行 Java。") from None
    try:
        info = inspect_java(java, required)
        _validate_jvm(_effective_jvm(jvm), info["major"])
        if kind == "args" and info["major"] < 9:
            raise PanelError("Java 8 不支持 @参数文件启动，未运行 Java。")
        # The version probe may take time. Refuse a plan whose source changed
        # during validation rather than bypassing new user startup instructions.
        if any(_digest(path) != digest for path, digest in watched.items()):
            raise PanelError("启动配置在 Java 检查期间发生变化，请重试；未运行 Java。")
        arguments = [str(info["path"]), *jvm, "-Dqizhang.panel.server_id=" + identifier]
        if kind == "args":
            arguments.append("@" + entry)
        elif kind == "classpath":
            arguments.extend(["-cp", os.pathsep.join(classpath), main])
        else:
            arguments.extend(["-jar", entry])
        arguments.extend(headless_args(core[0], game))
        environment = os.environ.copy()
        for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
            environment.pop(key, None)
        return arguments, environment
    except PanelError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise PanelError("原启动配置的 Java 检查未通过，未运行 Java：" + str(error)) from None
