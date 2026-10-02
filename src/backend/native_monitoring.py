# 七章控制面板 · © 2026 EeryFrank · https://github.com/EeryFrank
"""On-demand, bounded log deltas and lightweight metrics for native clients.

No worker, open file handle, process discovery, network call or growing history.
Lifecycle authority remains in ServerManager; these APIs only present samples.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import threading
import uuid

MAX_BUFFER_BYTES = 512 * 1024
MAX_LINE_BYTES = 16 * 1024
READ_BYTES = 64 * 1024
INITIAL_BYTES = 128 * 1024
MAX_LINES = 2000


class NativeMonitoring:
    def __init__(self, manager):
        self.manager = manager
        self.lock = threading.Lock()
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.lines = deque()
        self.buffer_bytes = 0
        self.streams = {}
        self.stream_choice = None
        self.process_identity = None
        self.notices = ()
        self.metrics_sampler = None
        self.metrics_lock = threading.Lock()

    def metrics(self):
        from server_manager import ProcessMetrics
        with self.metrics_lock:
            with self.manager._status_lock:
                pid = int(self.manager._status.get("pid", 0) or 0)
                running = bool(self.manager._status.get("running"))
                identity = self.manager._log_process_identity
            sample_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            result = {"pid": pid, "cpu_percent": 0.0, "memory_mb": 0.0,
                      "uptime_seconds": 0, "metrics_valid": False, "metrics_updated_at": sample_at}
            if running and pid and identity and identity[0] == pid and identity[1]:
                if self.metrics_sampler is None:
                    self.metrics_sampler = ProcessMetrics()
                # Never accumulate old process lifetimes when a server restarts.
                if set(self.metrics_sampler._samples) - {pid}:
                    self.metrics_sampler._samples.clear()
                sample = self.metrics_sampler.get(pid)
                created = sample.get("created_at_unix")
                if created is not None and abs(created - identity[1]) < .001:
                    result.update({key: sample[key] for key in ("cpu_percent", "memory_mb", "uptime_seconds")})
                    result["metrics_valid"] = True
                else:
                    self.metrics_sampler._samples.clear()
            return {"server": result, "updated_at": sample_at, "available": result["metrics_valid"]}

    def _reset(self):
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.lines.clear()
        self.buffer_bytes = 0
        self.streams.clear()
        self.notices = ()

    def _append(self, text, tag=""):
        text = text.rstrip("\r")
        if not text:
            return
        encoded = (tag + text).encode("utf-8", errors="replace")
        if len(encoded) > MAX_LINE_BYTES:
            encoded = encoded[:MAX_LINE_BYTES]
            text = encoded.decode("utf-8", errors="ignore") + " …[单行过长，已截断]"
            encoded = text.encode("utf-8")
        else:
            text = tag + text
        self.sequence += 1
        self.lines.append((self.sequence, text, len(encoded)))
        self.buffer_bytes += len(encoded)
        while len(self.lines) > MAX_LINES or self.buffer_bytes > MAX_BUFFER_BYTES:
            self.buffer_bytes -= self.lines.popleft()[2]

    def _paths(self):
        root = self.manager.server_root
        latest = self.manager.latest_log_path
        # Bootstrap stdout matters before Minecraft creates its own log.
        use_stdout = not latest.is_file() or self.manager._startup_waiting
        return [(latest, "")] + (
            [(root / "logs/panel-launcher.stdout.log", "[启动器/INFO] ")] if use_stdout else []
        ) + [(root / "logs/panel-launcher.stderr.log", "[启动器/ERROR] ")]

    def _read_streams(self):
        from server_manager import decode_server_log
        paths = self._paths()
        choice = tuple(str(path) for path, _ in paths)
        identity = self.manager._log_process_identity
        if choice != self.stream_choice or identity != self.process_identity:
            self._reset()
            self.stream_choice, self.process_identity = choice, identity
        changed = False
        for path, _ in paths:
            old = self.streams.get(str(path))
            if old is None:
                continue
            try:
                stat = path.stat()
                if old["identity"] != (stat.st_dev, stat.st_ino) or stat.st_size < old["offset"]:
                    changed = True
            except FileNotFoundError:
                changed = True
        if changed:
            self._reset()
        more = False
        for path, tag in paths:
            try:
                with path.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    key = str(path)
                    state = self.streams.get(key)
                    initial = state is None
                    if initial:
                        offset = max(0, stat.st_size - INITIAL_BYTES)
                        state = {"identity": (stat.st_dev, stat.st_ino), "offset": offset, "partial": b""}
                        self.streams[key] = state
                    else:
                        offset = state["offset"]
                    stream.seek(offset)
                    data = stream.read(INITIAL_BYTES if initial else READ_BYTES)
                    state["offset"] = stream.tell()
                    more |= state["offset"] < stat.st_size
                if initial and offset:
                    # A tail window must not start in the middle of a UTF-8 line.
                    data = data.split(b"\n", 1)[1] if b"\n" in data else b""
                content = state["partial"] + data
                pieces = content.split(b"\n")
                state["partial"] = pieces.pop()[-MAX_LINE_BYTES:]
                for line in pieces:
                    self._append(decode_server_log(line), tag)
            except FileNotFoundError:
                self.streams.pop(str(path), None)
        notices = tuple(self.manager._startup_notices)
        if notices != self.notices:
            overlap = 0
            for size in range(min(len(notices), len(self.notices)), 0, -1):
                if self.notices[-size:] == notices[:size]:
                    overlap = size
                    break
            for line in notices[overlap:]:
                self._append(str(line))
            self.notices = notices
        return more

    def poll_logs(self, cursor=None, lines=200, query="", level=""):
        if type(lines) is not int or not 20 <= lines <= 1000:
            raise ValueError("日志显示行数必须在 20～1000 之间。")
        if not isinstance(query, str) or len(query) > 256 or not isinstance(level, str) or len(level) > 16:
            raise ValueError("日志筛选条件无效。")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 128):
            raise ValueError("日志游标无效。")
        query, level = query.strip().lower(), level.strip().upper()
        signature = hashlib.sha256((str(lines) + "\0" + query + "\0" + level).encode()).hexdigest()[:16]
        with self.lock:
            truncated = self._read_streams()
            parts = (cursor or "").split(":")
            valid = (len(parts) == 3 and parts[0] == self.epoch and parts[2] == signature
                     and parts[1].isdigit() and 0 <= int(parts[1]) <= self.sequence)
            position = int(parts[1]) if valid else 0
            if valid and self.lines and position < self.lines[0][0] - 1:
                valid = False
            reset = not valid
            values = [text for sequence, text, _ in self.lines
                      if (reset or sequence > position)
                      and (not query or query in text.lower())
                      and (not level or f"/{level}]" in text.upper())]
            if len(values) > lines:
                truncated = True
            return {"cursor": f"{self.epoch}:{self.sequence}:{signature}",
                    "reset": reset, "lines": values[-lines:], "truncated": truncated}


def for_manager(manager):
    # NativeHost serializes route selection; guard also supports direct callers.
    with manager._status_lock:
        monitoring = getattr(manager, "_native_monitoring", None)
        if monitoring is None:
            monitoring = NativeMonitoring(manager)
            manager._native_monitoring = monitoring
        return monitoring
