"""Windows logon startup for 七章控制面板; owned by EeryFrank.
Project: https://github.com/EeryFrank
Administrator startup is configured only after the Windows elevation consent.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
import xml.etree.ElementTree as ET


class StartupError(ValueError):
    pass


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _powershell(script, elevated=False):
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    if elevated and not ctypes.windll.shell32.IsUserAnAdmin():
        wrapper = ("$ErrorActionPreference='Stop';try{$p=Start-Process -FilePath 'powershell.exe' "
                   "-ArgumentList @('-NoProfile','-NonInteractive','-EncodedCommand'," + ps_quote(encoded) + ") "
                   "-Verb RunAs -WindowStyle Hidden -PassThru -Wait;exit $p.ExitCode}catch{exit 1223}")
        encoded = base64.b64encode(wrapper.encode("utf-16le")).decode("ascii")
        command[-1] = encoded
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=NO_WINDOW, timeout=180, check=False)
    if result.returncode:
        raise StartupError("Windows 未完成开机启动权限配置。管理员模式需要授权；取消授权时不会保存新设置。")
    return result.stdout.decode("utf-8-sig", errors="replace").strip()


def current_sid():
    output = _powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);[Security.Principal.WindowsIdentity]::GetCurrent().User.Value")
    if not output.startswith("S-1-") or any(c not in "S-0123456789" for c in output):
        raise StartupError("无法读取当前 Windows 账号标识。")
    return output


def administrator_account():
    return _powershell("([Security.Principal.WindowsIdentity]::GetCurrent().Groups.Value -contains 'S-1-5-32-544')").casefold() == "true"


def task_xml(executable, state_root, sid):
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    def node(parent, name, text=None, **attrs):
        result = ET.SubElement(parent, "{" + namespace + "}" + name, attrs)
        if text is not None:
            result.text = str(text)
        return result
    root = ET.Element("{" + namespace + "}Task", {"version": "1.4"})
    info = node(root, "RegistrationInfo")
    node(info, "Author", "EeryFrank")
    node(info, "Description", "七章控制面板 · 当前 Windows 账号登录后按指定权限启动")
    triggers = node(root, "Triggers")
    trigger = node(triggers, "LogonTrigger")
    node(trigger, "Enabled", "true")
    node(trigger, "UserId", sid)
    node(trigger, "Delay", "PT5S")
    principal = node(node(root, "Principals"), "Principal", id="Author")
    node(principal, "UserId", sid)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "HighestAvailable")
    settings = node(root, "Settings")
    for key, value in (("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                       ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
                       ("ExecutionTimeLimit", "PT0S"), ("Enabled", "true")):
        node(settings, key, value)
    action = node(node(root, "Actions", Context="Author"), "Exec")
    node(action, "Command", str(Path(executable).resolve()))
    node(action, "Arguments", subprocess.list2cmdline(["--autostart", "--data-root", str(Path(state_root).resolve())]))
    node(action, "WorkingDirectory", str(Path(executable).resolve().parent))
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def set_shortcut(enabled, executable, state_root, task_name):
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True, exist_ok=True)
    link = startup / (task_name + ".lnk")
    if not enabled:
        link.unlink(missing_ok=True)
        return
    script = ("$ErrorActionPreference='Stop';$s=New-Object -ComObject WScript.Shell;"
              "$l=$s.CreateShortcut(" + ps_quote(link) + ");$l.TargetPath=" + ps_quote(executable) + ";"
              "$l.Arguments=" + ps_quote(subprocess.list2cmdline(["--autostart", "--data-root", str(state_root)])) + ";"
              "$l.WorkingDirectory=" + ps_quote(Path(executable).parent) + ";$l.Save()")
    _powershell(script)


def _write_record(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(enabled, permission, executable, state_root, shortcut_setter=None):
    if not isinstance(enabled, bool) or permission not in {"normal", "administrator"}:
        raise StartupError("开机启动权限必须选择普通权限或管理员权限。")
    executable, state_root = Path(executable).resolve(), Path(state_root).resolve()
    if not executable.is_file():
        raise StartupError("程序文件不存在，无法配置开机启动。")
    receipt_file = state_root / "startup-registration.json"
    pending_file = state_root / "startup-registration.pending.json"
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8")) if receipt_file.exists() else {}
        pending = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.exists() else {}
        if not isinstance(receipt, dict) or not isinstance(pending, dict):
            raise ValueError()
    except (ValueError, OSError):
        raise StartupError("开机启动记录损坏，请保留记录后修复。") from None
    task_name = receipt.get("task_name") or pending.get("task_name") or "QiZhangControlPanel-" + hashlib.sha256(str(state_root).casefold().encode("utf-8")).hexdigest()[:16]
    if not isinstance(task_name, str) or not task_name.startswith("QiZhangControlPanel-") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in task_name):
        raise StartupError("开机启动任务记录无效。")
    if pending.get("task_name") and pending["task_name"] != task_name:
        raise StartupError("未完成的开机启动任务记录不一致，请保留记录后修复。")
    had_task = bool(receipt.get("mode") == "administrator" and receipt.get("enabled") or pending.get("may_have_admin_task"))
    shortcut_setter = shortcut_setter or set_shortcut
    operation = {"task_name": task_name, "enabled": enabled, "mode": permission,
                 "may_have_admin_task": had_task or enabled and permission == "administrator"}
    if enabled and permission == "administrator":
        if not administrator_account():
            raise StartupError("管理员开机启动需要当前 Windows 账号属于管理员组；可改用普通权限启动。")
        xml = task_xml(executable, state_root, current_sid())
        encoded_xml = base64.b64encode(xml.encode("utf-8")).decode("ascii")
        script = ("$ErrorActionPreference='Stop';$xml=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(" + ps_quote(encoded_xml) + "));"
                  "Register-ScheduledTask -TaskName " + ps_quote(task_name) + " -Xml $xml -Force | Out-Null")
        # Record possible ownership before touching the OS. If a later shortcut
        # or receipt write fails, a subsequent disable still removes this task.
        _write_record(pending_file, operation)
        try:
            _powershell(script, elevated=True)
        except Exception:
            # A denied/cancelled registration must leave the previous receipt,
            # shortcut and any prior incomplete-operation record unchanged.
            if pending:
                _write_record(pending_file, pending)
            else:
                pending_file.unlink(missing_ok=True)
            raise
        shortcut_setter(False, executable, state_root, task_name)
    else:
        _write_record(pending_file, operation)
        if had_task:
            script = ("$ErrorActionPreference='Stop';$task=Get-ScheduledTask -TaskName " + ps_quote(task_name) + " -ErrorAction SilentlyContinue;"
                      "if($task){Unregister-ScheduledTask -TaskName " + ps_quote(task_name) + " -Confirm:$false}")
            _powershell(script, elevated=True)
        shortcut_setter(enabled, executable, state_root, task_name)
    result = {"task_name": task_name, "enabled": enabled, "mode": permission,
              "executable": str(executable), "state_root": str(state_root)}
    _write_record(receipt_file, result)
    try:
        pending_file.unlink(missing_ok=True)
    except OSError:
        pass  # The committed receipt is authoritative; a stale recovery record is harmless.
    return result
