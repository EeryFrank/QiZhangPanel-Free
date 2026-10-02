# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Explicitly bind a preserved original launcher, without starting anything."""
import hashlib
import json
from pathlib import Path
import re

from server_manager import PanelError

MANAGED = "qizhang-managed-start.bat"
PAUSE_NAME = "关闭服务器：切换原启动文件"
CLEAR_RECORD_ACKNOWLEDGEMENT = "已关闭所有原启动器和服务器"


def _root(manager):
    path = Path(manager.server_root)
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise PanelError("服务器路径包含链接，不能自动切换启动文件。")
    return path.resolve()


def _record(manager):
    root = _root(manager)
    path = root / "qizhang-import.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise PanelError("没有可验证的原始导入记录，不能自动切换启动文件。")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    plan = data.get("startup_adaptation") if isinstance(data, dict) else None
    if not isinstance(plan, dict) or plan.get("enabled") is not True:
        raise PanelError("当前服务器没有启用七章专属启动适配。")
    sources = plan.get("original_scripts", [])
    if not isinstance(sources, list) or len(sources) > 32:
        raise PanelError("原启动文件记录格式无效。")
    return root, sources


def _item(manager, root, source):
    if isinstance(source, dict) and source.get("blocked_reason"):
        raise PanelError(str(source["blocked_reason"]))
    if not isinstance(source, dict) or source.get("can_run_original") is not True:
        raise PanelError("该文件不是可直接绑定的原始 BAT/CMD。")
    name, digest = source.get("path"), source.get("sha256")
    if (not isinstance(name, str) or not name or Path(name).name != name
            or any(char in name for char in '/\\:%!\r\n"&|<>^')
            or Path(name).suffix.lower() not in {".bat", ".cmd"}
            or name.lower() == MANAGED or source.get("format") != Path(name).suffix.lower().lstrip(".")
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
        raise PanelError("原启动文件记录不是安全的根目录 BAT/CMD。")
    path = root / name
    if (path.is_symlink() or getattr(path, "is_junction", lambda: False)() or not path.is_file()
            or not path.resolve().is_relative_to(root) or path.stat().st_size > 128 * 1024):
        raise PanelError("原启动文件不存在、过大或已变为链接。")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest.lower():
        raise PanelError("原启动文件内容已变化，不能沿用之前的恢复选项。")
    identity = json.dumps([str(manager.server_id), name, actual], ensure_ascii=False, separators=(",", ":"))
    return {"id": "original-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
            "label": name, "source": name,
            "reason": "已核对导入时的原文件哈希；仅切换绑定，需要你另行点击启动。"}


def alternatives(manager):
    """Read-only: never pause a watchdog, change files or probe a running JVM."""
    current = str(manager.launch_script)
    result = {"available": False, "message": "", "current": current, "items": []}
    if current != MANAGED or not getattr(manager, "startup_adaptation_enabled", False):
        result["message"] = "当前使用原启动方式，或未启用七章专属适配，无需切换。"
        return result
    try:
        root, sources = _record(manager)
        seen, rejected, blocked = set(), 0, []
        for source in sources:
            try:
                item = _item(manager, root, source)
                if item["id"] not in seen:
                    result["items"].append(item)
                    seen.add(item["id"])
            except (OSError, ValueError, PanelError):
                rejected += 1
                if isinstance(source, dict) and source.get("blocked_reason"):
                    blocked.append(str(source["blocked_reason"]))
        result["available"] = bool(result["items"])
        result["message"] = ("可切换到导入时保留的原启动文件；切换不会自动开服。" if result["available"]
                             else "没有可验证的原始 BAT/CMD 文件；请在服务器设置中检查原启动入口。")
        if rejected:
            result["message"] += " 部分原文件已变化或不符合要求，未列入选项。"
        if blocked:
            result["message"] += " " + "；".join(dict.fromkeys(blocked))
    except (OSError, ValueError, PanelError) as error:
        result["message"] = "无法读取可用的原启动文件：" + str(error)
    return result


def _idle_flags(manager):
    if manager._operation.get("active"):
        raise PanelError("服务器仍在执行操作，请结束后再切换启动文件。")
    if manager._shutdown_countdown.get("active"):
        raise PanelError("停服倒计时仍在执行，暂不能切换启动文件。")
    if manager.maintenance_flag_path.exists():
        raise PanelError("服务器正在维护、备份或恢复，暂不能切换启动文件。")
    if manager.starting_flag_path.exists() or manager._startup_waiting:
        raise PanelError("服务器仍在启动，请先停止启动并确认进程退出。")
    launcher = manager._startup_launcher
    if launcher is not None and launcher.poll() is None:
        raise PanelError("原启动进程尚未退出，暂不能切换启动文件。")


def _verify_stopped(manager):
    from native_managed_launch import owned_exit_snapshot
    _idle_flags(manager)
    try:
        pid = manager.validated_server_pid()
        if type(pid) is not int or pid < 0:
            raise ValueError("invalid PID result")
        if pid or manager._read_watchdog_pid(validate_command=True):
            raise PanelError("服务器或外部守护仍在运行，不能切换启动文件。")
        snapshot = owned_exit_snapshot(manager)
        if snapshot is None:
            snapshot = manager._startup_process_snapshot(force=True)
        if (not isinstance(snapshot, dict)
                or not {"java_pid", "launcher_pids", "watchdog_pids"}.issubset(snapshot)
                or snapshot["java_pid"] or snapshot["launcher_pids"] or snapshot["watchdog_pids"]):
            raise PanelError("无法确认本实例所有进程均已退出，未切换启动文件。")
    except PanelError:
        raise
    except Exception as error:
        try:
            manager.log("原启动文件切换核验失败：" + type(error).__name__ + ": " + str(error), "WARN")
        except Exception:
            pass
        raise PanelError("暂时无法确认服务器已完全停止，未切换启动文件。") from None


def use_alternative(manager, payload, persist_launcher):
    """Host must call through manager.run_direct_mutation; this never starts Java.

    Countdown/operation locks use the existing configuration lock order. The
    native watchdog generation is invalidated before the final absence check;
    a failed check leaves automatic retries paused, never reopening a server.
    """
    if not isinstance(payload, dict) or payload.get("confirmed") is not True:
        raise PanelError("请先确认仅切换到原启动文件；切换后需要手动启动服务器。")
    if not isinstance(payload.get("id"), str) or not payload["id"]:
        raise PanelError("请选择已验证的原启动文件。")
    if not callable(persist_launcher):
        raise PanelError("启动文件绑定保存接口不可用。")
    with manager._shutdown_countdown_lock, manager._operation_lock:
        listing = alternatives(manager)
        matches = [item for item in listing["items"] if item["id"] == payload["id"]]
        if not listing["available"] or len(matches) != 1:
            raise PanelError("原启动文件选项已失效，请重新打开选项核对；未切换。")
        operation_id = payload.get("startup_operation_id")
        if operation_id is not None:
            current_id = str(manager._last_startup_operation.get("id", ""))
            if not isinstance(operation_id, str) or operation_id != current_id:
                raise PanelError("启动状态已经变化，此次恢复提示已失效；请重新检查当前服务器。")
        _idle_flags(manager)
        guard = getattr(manager, "native_watchdog", None)
        if guard is not None:
            guard.operation_changed(True, PAUSE_NAME)
        _verify_stopped(manager)
        # Identity scans can take time. Re-read metadata/content and state after
        # them so a changed source or new startup cannot reuse an old selection.
        final = alternatives(manager)
        chosen = [item for item in final["items"] if item["id"] == payload["id"]]
        if not final["available"] or len(chosen) != 1:
            raise PanelError("核验期间原启动文件已变化，未切换；自动重试保持暂停。")
        _idle_flags(manager)
        selected = chosen[0]["source"]
        try:
            persist_launcher(selected)
        except Exception:
            raise PanelError("原启动文件绑定保存失败；未自动启动服务器，请检查服务器设置。") from None
        manager.launch_script = selected
        manager.jvm_args_path = manager.server_root / "user_jvm_args.txt"
        notice = "已切换为原启动文件“" + selected + "”。服务器尚未启动，请手动点击启动。"
        if guard is not None:
            notice += " 内置守护的自动重试已暂停。"
        return {"launch_script": selected, "started": False,
                "message": notice}


def clear_closed_launcher_record(manager, payload):
    """Cancel an old record on explicit user attestation, never infer GUI exit.

    The host must serialize this through run_direct_mutation. A retained Job,
    live Java, listener, active task or unknown query vetoes the confirmation.
    For old opaque launchers, the user's confirmation supplies the missing GUI
    knowledge; this must never be described as a complete process absence proof.
    No process is started, adopted, terminated or sent a game command.
    """
    if (not isinstance(payload, dict) or payload.get('confirmed') is not True
            or payload.get('acknowledgement') != CLEAR_RECORD_ACKNOWLEDGEMENT):
        raise PanelError('请确认原启动器和服务器均已关闭，并准确输入“' + CLEAR_RECORD_ACKNOWLEDGEMENT + '”。')
    from native_launch_job import snapshot as job_snapshot
    from native_managed_launch import _native_process_rows
    from server_manager import WindowsPortTable

    def idle_marker():
        if (manager._operation.get('active') or manager._shutdown_countdown.get('active')
                or manager._startup_waiting or manager.maintenance_flag_path.exists()):
            raise PanelError('服务器仍有操作、启动等待、倒计时或维护，未结束旧启动记录。')
        marker = manager.starting_flag_path
        if marker.is_symlink() or not marker.is_file():
            raise PanelError('没有可结束的普通旧启动记录；请刷新服务器状态。')
        launcher = manager._startup_launcher
        if launcher is not None and launcher.poll() is None:
            raise PanelError('本次启动器尚未退出，不能仅凭确认结束启动记录。')
        return marker.stat()

    def empty(snapshot):
        return (isinstance(snapshot, dict)
                and type(snapshot.get('java_pid')) is int and snapshot['java_pid'] == 0
                and isinstance(snapshot.get('launcher_pids'), (list, tuple)) and not snapshot['launcher_pids']
                and isinstance(snapshot.get('watchdog_pids'), (list, tuple)) and not snapshot['watchdog_pids'])

    def check_processes():
        pid = manager.validated_server_pid()
        watchdog = manager._read_watchdog_pid(validate_command=True)
        if type(pid) is not int or pid < 0 or type(watchdog) is not int or watchdog < 0:
            raise PanelError('进程身份核验结果不明，未结束旧启动记录。')
        if pid or watchdog:
            raise PanelError('服务器或外部守护仍在运行，未结束旧启动记录。')
        port, protocol = manager._runtime_endpoint()
        if type(port) is not int or not 1 <= port <= 65535 or protocol not in {'TCP', 'UDP'}:
            raise PanelError('配置的游戏端口或协议无效，未结束旧启动记录。')
        # Use the strict native table directly: a failed netstat fallback must
        # not be mistaken for an empty listening-port table.
        listener = WindowsPortTable.find_pid(port, protocol)
        if type(listener) is not int or listener < 0:
            raise PanelError('游戏端口状态不明，未结束旧启动记录。')
        if listener:
            raise PanelError('配置的游戏端口仍被进程监听或占用，未结束旧启动记录。')
        job = job_snapshot(manager)
        if ((getattr(manager, '_owned_launch_job', None) is not None and job is None)
                or job is not None and not empty(job)):
            raise PanelError('本次启动的受跟踪进程尚未全部退出或身份不明，未结束旧启动记录。')
        if not empty(manager._startup_process_snapshot(force=True)):
            raise PanelError('无法排除本实例仍有 Java、启动器或守护进程，未结束旧启动记录。')
        rows = _native_process_rows()
        if not isinstance(rows, list):
            raise PanelError('全局进程核验结果不明，未结束旧启动记录。')
        from native_platforms import process_images
        runtimes = {'java.exe', 'javaw.exe', 'bedrock_server.exe', 'php.exe'} | set(process_images(manager.platform))
        root = str(manager.server_root.resolve()).replace('/', '\\').lower()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                raise PanelError('全局进程信息不完整，未结束旧启动记录。')
            if row.get('exited'):
                continue
            if row['name'].lower() in runtimes:
                raise PanelError('检测到仍存活的游戏运行时进程，无法排除旧实例；请关闭相关 Java/服务端后再试。')
            command = str(row.get('command', '')).replace('/', '\\').lower()
            if root in command:
                raise PanelError('检测到仍引用此服务器目录的进程，未结束旧启动记录。')

    with manager._shutdown_countdown_lock, manager._operation_lock:
        try:
            before = idle_marker()
            guard = getattr(manager, 'native_watchdog', None)
            if guard is not None:
                guard.operation_changed(True, '关闭服务器：结束旧启动记录')
            # Two fresh reads also reject a runtime/listener that appears
            # during the first scan. Local operations remain serialized.
            check_processes()
            if idle_marker() != before:
                raise PanelError('核验期间旧启动记录发生变化，未结束该记录，请重新检查。')
            check_processes()
            if idle_marker() != before:
                raise PanelError('核验期间旧启动记录发生变化，未结束该记录，请重新检查。')
            manager._clear_inactive_startup()
            message = ('用户已确认原启动器和服务器全部关闭，已结束旧启动记录；'
                       '未接管、结束或启动任何进程。原启动失败记录保留。'
                       '对于未被旧版跟踪的原生启动器，此操作依据用户确认，不代表自动证明全部进程已退出。')
            if guard is not None:
                message += ' 内置守护自动重试已暂停。'
            manager._startup_notices.append('[面板/WARN] ' + message)
            manager.log(message, 'WARN')
            return {'cleared': True, 'started': False, 'source': 'user_confirmed_record', 'message': message}
        except PanelError:
            raise
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            raise PanelError('无法可靠读取当前进程、端口或旧启动记录，未结束该记录；请关闭相关进程后重试。') from None
