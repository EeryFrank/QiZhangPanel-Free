# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
"""Confirmed, asynchronous safe shutdown before the native host exits.

Normal interactive exit inspects loaded workspaces. Unattended update exit
also verifies every on-disk registration. Responses never identify accounts.
"""
from __future__ import annotations
import threading
from contextlib import ExitStack
from server_manager import PanelError
STOP_NAME = '安全关闭服务器'

class NativeExit:

    def __init__(self, host):
        self.host = host
        self._lock = threading.RLock()
        self._phase = 'idle'
        self._error = ''
        self._message = '退出前会检查所有已加载工作区的服务器。'
        self._total = 0
        self._completed = 0
        self._thread = None
        self._closing = threading.Event()
        self._paused = []
        self._update_committed = False

    @property
    def blocks_requests(self):
        with self._lock:
            return self._phase in {'stopping', 'ready', 'checking_update'}

    def _contexts(self):
        result, seen = ([], set())
        try:
            for registry in tuple(self.host.registries.values()):
                for context in registry.contexts():
                    if id(context.manager) not in seen:
                        seen.add(id(context.manager))
                        result.append(context)
        except Exception:
            raise PanelError('无法读取已加载服务器的状态，面板不会退出；请检查工作区状态。') from None
        return result

    @staticmethod
    def _summary(context):
        try:
            manager = context.manager
            value = manager.get_status()
            server = value.get('server', {})
            if server.get('starting') and (not value.get('operation', {}).get('active')) and (not value.get('shutdown_countdown', {}).get('active')):
                reconcile = getattr(manager, 'reconcile_startup_state', None)
                if callable(reconcile):
                    reconcile(force=True)
                    value = manager.get_status()
                    server = value.get('server', {})
            busy = bool(value.get('operation', {}).get('active') or value.get('shutdown_countdown', {}).get('active') or server.get('starting'))
            running = bool(server.get('running') or server.get('starting') or server.get('pid'))
            unknown = bool(server.get('status_known') is False or server.get('monitor_error'))
            return (running, busy, unknown)
        except Exception:
            raise PanelError('无法读取服务器状态，面板不会退出；请检查工作区状态。') from None

    def status(self):
        with self._lock:
            phase, completed, total = (self._phase, self._completed, self._total)
            error, message = (self._error, self._message)
        running, busy, unknown = (0, False, False)
        try:
            contexts = self._contexts()
            if phase in {'idle', 'failed'}:
                total = len(contexts)
            for context in contexts:
                live, working, uncertain = self._summary(context)
                running += int(live)
                busy = busy or working
                unknown = unknown or uncertain
            busy = busy or bool(self.host.busy())
        except Exception:
            busy, unknown = (True, True)
        if phase == 'idle' or (phase == 'failed' and (not error)):
            if unknown:
                message = '尚无法确认全部服务器的进程状态，面板暂不退出；请刷新服务器状态并查看启动日志。'
            elif busy:
                message = '服务器仍在启动或后台任务正在执行，面板暂不退出；请等待操作结束后重试。'
        if phase == 'ready':
            running = 0
        return {'active': phase == 'stopping', 'all_stopped': phase == 'ready' or (phase == 'idle' and (not running) and (not busy) and (not unknown)), 'phase': phase, 'running_count': running, 'total_count': total, 'completed_count': completed, 'busy': busy or phase == 'stopping', 'error': error, 'message': message}

    @staticmethod
    def _verified_pid(context, *, log_failure=True, strict=False):
        manager = context.manager
        try:
            pid = manager.validated_server_pid(strict=True) if strict else manager.validated_server_pid()
            if type(pid) is not int or pid < 0:
                raise ValueError()
            if pid:
                return pid
            from native_managed_launch import owned_exit_snapshot
            snapshot = owned_exit_snapshot(manager)
            if snapshot is None:
                snapshot = manager._startup_process_snapshot(force=True)
            if not isinstance(snapshot, dict) or not {'java_pid', 'launcher_pids', 'watchdog_pids'}.issubset(snapshot) or snapshot['java_pid'] or snapshot['launcher_pids'] or snapshot['watchdog_pids']:
                raise ValueError('process snapshot unknown or instance activity remains')
            return 0
        except Exception as error:
            if log_failure:
                try:
                    manager.log('安全退出进程核验未通过：' + type(error).__name__ + ': ' + str(error), 'WARN')
                except Exception:
                    pass
            raise PanelError('无法确认某个服务器的进程状态，面板不会退出；请刷新对应工作区并检查启动日志。') from None

    def _preflight(self, contexts):
        try:
            host_busy = self.host.busy()
        except Exception:
            raise PanelError('无法确认后台任务状态，面板不会退出；请检查工作区状态。') from None
        try:
            if host_busy:
                raise PanelError('后台安装、备份、恢复或停服通知仍在执行，请完成后再退出。')
            running = []
            for context in contexts:
                _, busy, _ = self._summary(context)
                if busy:
                    raise PanelError('服务器仍在启动或执行其他操作，请完成后再退出。')
                pid = self._verified_pid(context)
                if pid:
                    running.append(context)
            return running
        except PanelError:
            raise
        except Exception:
            raise PanelError('无法读取全部服务器的状态，面板不会退出；请检查工作区状态。') from None

    def prepare(self, confirmed: bool):
        if confirmed is not True:
            raise PanelError('请先明确确认安全停止全部服务器后退出。')
        with self._lock:
            if self._closing.is_set():
                raise PanelError('面板后台正在关闭。')
            if self._phase in {'stopping', 'ready'}:
                return self.status()
            contexts = self._contexts()
            self._preflight(contexts)
            self._phase, self._error = ('stopping', '')
            self._total, self._completed = (len(contexts), 0)
            self._message = '正在安全停止服务器，请等待保存完成。'
            self._thread = threading.Thread(target=self._run, args=(contexts,), name='QiZhang-Exit', daemon=False)
            try:
                self._thread.start()
            except Exception:
                self._phase, self._error = ('failed', '无法启动安全退出任务，面板仍保持运行。')
                self._message = self._error
                raise PanelError(self._error) from None
        return self.status()

    def _run(self, contexts):
        try:
            self._preflight(contexts)
            for index, context in enumerate(contexts):
                if self._closing.is_set():
                    raise PanelError('后台正在关闭，未继续发送停服命令。')
                with self._lock:
                    self._message = '正在安全停止服务器，请等待保存完成。'
                if self._verified_pid(context):
                    context.manager.run_operation_sync(STOP_NAME, context.manager.safe_stop_server)
                for attempt in range(10):
                    try:
                        if self._verified_pid(context):
                            raise PanelError('原服务器停服后仍有活动进程，面板不会退出。')
                        break
                    except PanelError:
                        if attempt == 9:
                            raise
                        if self._closing.wait(0.2):
                            raise PanelError('后台正在关闭。')
                with self._lock:
                    self._completed = index + 1
            if self.host.busy() or any((self._verified_pid(context) for context in contexts)):
                raise PanelError('退出前检测到新的服务器活动，面板仍保持运行。')
            with self._lock:
                self._phase = 'ready'
                self._message = '服务器已停止，可以退出七章控制面板。'
        except Exception:
            with self._lock:
                self._phase = 'failed'
                self._error = self._message = '安全退出未完成，面板仍保持运行；请在工作区检查操作状态和保存日志。'

    def finish(self):
        with self._lock:
            if self._phase == 'stopping':
                raise PanelError('服务器仍在安全停止，请等待完成后退出。')
            contexts = self._contexts()
            if self._preflight(contexts):
                raise PanelError('仍有服务器运行，请先确认安全停止后退出。')
            self._phase, self._total, self._completed = ('ready', len(contexts), len(contexts))
            self._message = '服务器已停止，七章控制面板正在退出。'
            self.host.exiting = True
        return self.status()

    def close(self):
        """Call before Host.close tears down managers or registries.

        A stop already in progress is allowed to finish its save/wait. No new
        stop is submitted once closing starts.
        """
        self._closing.set()
        with self._lock:
            worker = self._thread
        if worker is not None and worker is not threading.current_thread():
            worker.join()
