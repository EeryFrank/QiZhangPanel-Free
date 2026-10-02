# 七章控制面板项目归属：EeryFrank。项目主页：https://github.com/EeryFrank
"""Optional installer integration; does not start the panel or game servers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_startup


def checked_path(path):
    path = Path(os.path.abspath(path))
    if path.resolve() != path:
        raise ValueError("安装选项目录不能包含目录联接或符号链接。")
    return path


def has_accounts(state):
    file = state / "accounts.json"
    if not file.exists():
        return False
    try:
        record = json.loads(file.read_text(encoding="utf-8-sig"))
        return not isinstance(record, dict) or not isinstance(record.get("accounts"), list) or bool(record["accounts"])
    except (OSError, ValueError):
        # Never replace existing account preferences when the repository is damaged.
        return True


def desktop_shortcut(executable, desktop):
    desktop = checked_path(desktop)
    desktop.mkdir(parents=True, exist_ok=True)
    chosen = desktop / "七章控制面板.lnk"
    # Preserve another installation's shortcut instead of silently retargeting it.
    for index in range(1, 100):
        if index > 1:
            chosen = desktop / ("七章控制面板 (" + str(index) + ").lnk")
        checked_path(chosen)
        if not chosen.exists():
            break
        current = native_startup._powershell(
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
            "$s=New-Object -ComObject WScript.Shell;$s.CreateShortcut(" + native_startup.ps_quote(chosen) + ").TargetPath")
        if os.path.normcase(current) == os.path.normcase(str(executable)):
            break
    else:
        raise ValueError("桌面存在过多同名快捷方式，请先整理后重试。")
    temporary = chosen.with_name(chosen.stem + "." + uuid.uuid4().hex + ".tmp.lnk")
    script = ("$ErrorActionPreference='Stop';$s=New-Object -ComObject WScript.Shell;"
              "$l=$s.CreateShortcut(" + native_startup.ps_quote(temporary) + ");"
              "$l.TargetPath=" + native_startup.ps_quote(executable) + ";"
              "$l.WorkingDirectory=" + native_startup.ps_quote(executable.parent) + ";"
              "$l.IconLocation=" + native_startup.ps_quote(str(executable) + ",0") + ";"
              "$l.Description='七章控制面板 · EeryFrank';$l.Save()")
    try:
        native_startup._powershell(script)
        temporary.replace(chosen)
    finally:
        temporary.unlink(missing_ok=True)
    return str(chosen)


def apply_options(target, startup, desktop, desktop_directory):
    if not isinstance(startup, bool) or not isinstance(desktop, bool):
        raise ValueError("安装选项必须是布尔值。")
    target = checked_path(target)
    executable = checked_path(target / "七章控制面板.exe")
    if not executable.is_file() or not (target / "portable.flag").is_file():
        raise ValueError("请先完成七章控制面板程序文件安装。")
    state = checked_path(target / "data")
    state.mkdir(parents=True, exist_ok=True)
    for name in ("accounts.json", "installation-consent.json", "installer-startup-pending.json", "startup-registration.json", "startup-registration.pending.json"):
        checked_path(state / name)
    result = {"warnings": [], "startup_applied": False, "startup_preserved": has_accounts(state), "desktop_shortcut": ""}
    if not result["startup_preserved"]:
        try:
            if startup or (state / "startup-registration.json").exists() or (state / "startup-registration.pending.json").exists():
                native_startup.configure(startup, "normal", executable, state)
            # Only the first account may consume this once; later accounts remain independent.
            native_startup._write_record(state / "installer-startup-pending.json",
                                         {"schema": 1, "owner": "QiZhangInstaller", "enabled": startup, "mode": "normal"})
            result["startup_applied"] = True
        except Exception as error:
            result["warnings"].append("程序已安装，但开机启动选项未完整保存：" + str(error) + "。可在面板软件设置中调整。")
    if desktop:
        try:
            result["desktop_shortcut"] = desktop_shortcut(executable, desktop_directory)
        except Exception as error:
            result["warnings"].append("程序已安装，但桌面图标创建失败：" + str(error))
    try:
        disclaimer = target / "免责说明.md"
        native_startup._write_record(state / "installation-consent.json", {
            "schema": 1, "action": "clicked_install", "accepted_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer_sha256": hashlib.sha256(disclaimer.read_bytes()).hexdigest(),
            "requested_startup": startup, "requested_desktop_shortcut": desktop})
    except Exception as error:
        result["warnings"].append("安装说明记录未能保存：" + str(error))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--startup", choices=("true", "false"), required=True)
    parser.add_argument("--desktop", choices=("true", "false"), required=True)
    parser.add_argument("--desktop-directory", required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args()
    try:
        result = apply_options(args.target, args.startup == "true", args.desktop == "true", args.desktop_directory)
    except Exception as error:
        result = {"warnings": ["安装选项未完成：" + str(error)]}
    Path(args.result_file).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
