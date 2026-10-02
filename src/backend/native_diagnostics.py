# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""On-demand, bounded support reports. Never collect credentials or whole folders."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

SECRET = re.compile(r"password|passwd|secret|token|api[_-]?key|authorization|cookie|密钥|密码", re.I)
LOG_LIMIT = 96 * 1024


def scrub(value, root=None):
    text = str(value)
    if root:
        for path in (str(root), str(root).replace("\\", "/")):
            text = re.sub(re.escape(path), "<SERVER>", text, flags=re.I)
    # Remove complete lines with credential labels rather than guessing quoting.
    text = "\n".join("[已隐藏可能包含凭据的一行]" if SECRET.search(line) else line
                     for line in text.splitlines())
    text = re.sub(r"QZ1\.[A-Fa-f0-9]{64}\.[A-Za-z0-9_-]{43}", "<PAIRING-KEY>", text)
    text = re.sub(r"https?://\S+", "<URL>", text)
    text = re.sub(r"(?i)[A-Z]:[\\/][^\r\n\"<>|]*", "<LOCAL-PATH>", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<IP>", text)
    text = re.sub(r"(?i)(?<!\w)(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.%]+", "<IP>", text)
    text = re.sub(r"[A-Za-z0-9_+./=-]{40,}", "<LONG-VALUE>", text)
    return text[:LOG_LIMIT]


def command_channel(manager, state=None):
    """Report capability, without opening RCON, attaching Java or sending a probe."""
    state = state or {}
    result = {"id": "unverified", "label": "备用通道未验证", "ready": False,
              "note": "提交命令不代表服务端已执行；结果以本次日志为准。"}
    pid = state.get("pid")
    owned = getattr(manager, "_owned_direct_launch", None)
    if owned is not None:
        try:
            from native_console_pipe import _owned
            if _owned(manager, owned.pid) is owned:
                result.update(id="stdin", label="面板托管标准输入", ready=True)
                pid = owned.pid
        except Exception:
            result.update(id="unavailable", label="原进程输入通道已关闭")
    elif not state.get("running") and not state.get("starting"):
        result.update(id="offline", label="停服中，开服后建立通道")
    receipt = getattr(manager, "_last_command_submission", None)
    if isinstance(receipt, dict) and receipt.get("pid") == pid and state.get("running"):
        result["last_submission"] = {key: receipt[key] for key in ("channel", "submitted_at", "execution_confirmed") if key in receipt}
    return result


def record_submission(manager, pid, channel):
    manager._last_command_submission = {
        "pid": pid, "channel": channel,
        "submitted_at": datetime.now(timezone.utc).isoformat(), "execution_confirmed": False,
    }


def collect(manager, definition, version, include_logs=False):
    if type(include_logs) is not bool:
        raise ValueError("日志选项格式无效。")
    root = Path(manager.server_root).resolve()
    snapshot = manager.get_status()
    state, operation = snapshot.get("server", {}), snapshot.get("operation", {})
    profile = manager.platform_profile()
    report = {
        "schema": 1, "panel_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": str(definition.get("platform", "")),
        "runtime": profile.get("runtime"),
        "template_version": profile.get("template_version"),
        "capabilities": profile.get("capabilities", {}),
        "server": {key: state.get(key) for key in (
            "state", "running", "ready", "starting", "status_known", "status_stale",
            "sample_age_seconds", "uptime_seconds", "memory_mb", "cpu_percent")},
        "operation": {key: scrub(operation.get(key, ""), root) for key in ("name", "message", "started_at", "finished_at")},
        "command_channel": command_channel(manager, state),
        "startup": {"script": scrub(Path(manager.launch_script).name, root),
                    "adapted": bool(getattr(manager, "startup_adaptation_enabled", False)),
                    "runtime_file": Path(getattr(manager, "java_path", "")).name},
        "files": [], "logs_included": include_logs,
        "privacy": "不包含账号文件、环境变量、机器人或穿透配置、原始启动参数、存档和玩家名单。日志按规则脱敏；导出前请检查预览。",
    }
    # Hash explicit small launch manifests only; never walk worlds/mod folders.
    for name in ("qizhang-server-launch.json", "qizhang-platform-launch.json", "qizhang-managed-launch.json"):
        file = root / name
        if file.is_file() and not file.is_symlink() and file.resolve().parent == root:
            size = file.stat().st_size
            if size <= 256 * 1024:
                report["files"].append({"name": name, "bytes": size, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    log = ""
    if include_logs:
        # Check credential labels before clipping: truncation can otherwise
        # remove a label near the start but retain its secret value at the end.
        excerpts = []
        for line in manager.get_logs(150):
            text = str(line)
            excerpts.append("[已隐藏可能包含凭据的一行]" if SECRET.search(text) else text[-4096:])
        log = scrub("\n".join(excerpts)[-LOG_LIMIT:], root)
    return {"report": report, "logs": log}


def archive(document):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as packed:
        packed.writestr("diagnostics.json", json.dumps(document["report"], ensure_ascii=False, indent=2))
        if document["report"]["logs_included"]:
            packed.writestr("recent-redacted.log", document["logs"])
    content = output.getvalue()
    if len(content) > 256 * 1024:
        raise ValueError("诊断数据超过导出限制，请关闭日志选项后重试。")
    return {"filename": "QiZhang-diagnostics-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip",
            "archive_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest()}
