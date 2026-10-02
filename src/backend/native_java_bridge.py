# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Resolve the bundled Java 8 path bridge without losing its Unicode contract.

The bridge prepares its own private ASCII junction and temporary directory.
Only its explicit path-info protocol is queried; no original GUI is launched.
The panel then owns the actual JVM and its stdin, not the C# java.exe wrapper.
"""
import os
from pathlib import Path
import re
import subprocess


class LaunchPlan(tuple):
    def __new__(cls, arguments, environment, *, cwd):
        value = super().__new__(cls, (arguments, environment))
        value.cwd = Path(cwd)
        return value


def rewrite_argument(value, root, alias):
    # Match only this root at an argument/property/classpath boundary. Changing
    # separators in the whole value corrupts URLs and similarly named roots.
    escaped_root = r'[\\/]'.join(re.escape(part) for part in re.split(r'[\\/]', str(root)))
    pattern = re.compile(r'(?<![^=;:\"\'\s])' + escaped_root + r'(?=$|[\\/;\"\'])', re.I)
    return pattern.sub(lambda _: str(alias), str(value))


def resolve_launch(manager, launch):
    if launch is None:
        return None
    arguments, environment = launch
    root = manager.server_root.resolve()
    bridge = root / "runtime/java8-bridge/bin/java.exe"
    if not arguments or Path(arguments[0]).resolve() != bridge.resolve() or not bridge.is_file():
        return launch
    from server_manager import PanelError
    from native_server_install import inspect_java
    try:
        result = subprocess.run([str(bridge), "--qizhang-path-info"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8-sig", errors="strict",
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode != 0:
            raise ValueError("路径桥接初始化失败：" + result.stderr.strip()[-1000:])
        info = {}
        for row in result.stdout.splitlines():
            key, separator, value = row.partition("=")
            if not separator or key in info:
                raise ValueError("路径桥接返回了无效字段")
            info[key] = value
        if set(info) != {"SERVER_ROOT", "JAVA_ROOT_ALIAS", "JAVA_EXECUTABLE", "TEMP_DIRECTORY"}:
            raise ValueError("路径桥接协议不匹配")
        alias, java, temporary = (Path(info[key]) for key in ("JAVA_ROOT_ALIAS", "JAVA_EXECUTABLE", "TEMP_DIRECTORY"))
        if (Path(info["SERVER_ROOT"]).resolve() != root or not alias.is_absolute()
                or alias.resolve() != root or not java.is_absolute()
                or java.resolve() != (root / "runtime/java8/bin/java.exe").resolve()
                or not java.is_file() or not temporary.is_absolute() or not temporary.is_dir()
                or not str(alias).isascii() or not str(java).isascii() or not str(temporary).isascii()):
            raise ValueError("路径桥接返回的目录或 Java 与当前实例不一致")
        inspect_java(java, 8)
        # Respect the bridge's argument-boundary rules; a similarly named
        # directory outside this instance must never be rewritten.
        rewritten = [rewrite_argument(value, root, alias) for value in arguments[1:]]
        argv = [str(java), "-Djava.io.tmpdir=" + str(temporary),
                "-Dorg.sqlite.tmpdir=" + str(temporary), *rewritten]
        env = dict(environment if environment is not None else os.environ)
        env["TEMP"] = env["TMP"] = str(temporary)
        return LaunchPlan(argv, env, cwd=alias)
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as error:
        raise PanelError("无法安全接管整合包的 Java 路径桥接，未启动服务端：" + str(error)) from None
