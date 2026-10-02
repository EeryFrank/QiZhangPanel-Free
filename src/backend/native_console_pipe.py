# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Demand-only stdin delivery to the exact Java child owned by this panel.

A successful write means submitted to stdin, not that Minecraft executed it.
There is one bounded in-flight write; uncertainty never retries via another route.
"""
import threading

from native_managed_launch import OwnedLaunch, _handle_identity, _kernel


class ConsolePipeError(RuntimeError):
    pass


def _owned(manager, pid):
    owned = getattr(manager, '_owned_direct_launch', None)
    if not isinstance(owned, OwnedLaunch):
        return None
    if (owned.process is not manager._startup_launcher or owned.pid != pid
            or owned.server_id != manager.server_id or owned.root != manager.server_root.resolve()
            or owned.launcher != manager.launch_script or tuple(owned.process.args) != owned.arguments):
        raise ConsolePipeError('服务器进程身份已变化，未发送命令。请刷新服务器状态。')
    actual, birth, exited = _handle_identity(_kernel(), int(owned.process._handle))
    if (actual, birth) != (owned.pid, owned.birth) or exited:
        raise ConsolePipeError('原服务器进程已退出或身份变化，未发送命令。')
    if owned.process.stdin is None or owned.process.stdin.closed:
        raise ConsolePipeError('服务器标准输入已关闭，未发送命令。请检查日志后重新开服。')
    return owned


def send_command(manager, pid, command, *, timeout=5.0):
    if type(pid) is not int or pid <= 0 or not isinstance(command, str) or not command.strip() or len(command) > 2000 or any(c in command for c in '\r\n\0'):
        raise ConsolePipeError('服务器命令或进程标识无效。')
    try:
        owned = _owned(manager, pid)
    except (OSError, ValueError, AttributeError) as error:
        raise ConsolePipeError('无法确认标准输入所属的服务器进程，未发送命令。') from error
    if owned is None:
        return False
    # The lock is created with the manager. It does not add an idle worker.
    with manager._console_pipe_lock:
        previous = getattr(manager, '_console_pipe_pending', None)
        if previous is not None and not previous['done'].is_set():
            raise ConsolePipeError('上一条标准输入命令仍等待写入；本次未发送，请查看服务器是否卡住。')
        pending = {'done': threading.Event(), 'error': None}
        manager._console_pipe_pending = pending
        data = (command + '\n').encode('utf-8')

        def write():
            try:
                if _owned(manager, pid) is not owned:
                    raise ConsolePipeError('服务器启动实例已变化，未发送命令。')
                written = owned.process.stdin.write(data)
                if written != len(data):
                    raise ConsolePipeError('命令未完整写入，执行状态未知；未自动重试，请先检查控制台。')
                owned.process.stdin.flush()
            except Exception as error:
                pending['error'] = error
            finally:
                pending['done'].set()

        threading.Thread(target=write, name='QiZhang-Console-Write', daemon=True).start()
        if not pending['done'].wait(timeout):
            raise ConsolePipeError('写入服务器标准输入超时，命令可能尚在等待或已经提交；未自动重试，请先查看控制台。')
        if pending['error'] is not None:
            raise ConsolePipeError('服务器标准输入命令未确认提交；未切换通道或重试，请先查看控制台。' + str(pending['error'])) from pending['error']
        return True
