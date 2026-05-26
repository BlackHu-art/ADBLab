"""
统一管理长生命周期子进程：monkey / logcat / 录屏 / scrcpy 等。

全项目所有 subprocess.Popen 入口集中在此。
"""

import subprocess
import threading

from utils.adb_resolver import adb_path

from .command_runner import CF


class ProcessRunner:
    """统一管理后台子进程，支持按 key 启动/停止/轮询。

    用法:
        self._procs = ProcessRunner()
        proc = self._procs.start("logcat_192.168.1.1", ["adb", "logcat"], stdout=fh)
        ...
        self._procs.stop("logcat_192.168.1.1")
    """

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(self, key: str, cmd: list[str], stdout=None, stderr=None) -> subprocess.Popen:
        """启动子进程，同名 key 会先停止旧进程。"""
        stdout = subprocess.DEVNULL if stdout is None else stdout
        stderr = subprocess.DEVNULL if stderr is None else stderr
        proc = subprocess.Popen(self._resolve_cmd(cmd), stdout=stdout, stderr=stderr, creationflags=CF)
        with self._lock:
            old_proc = self._procs.pop(key, None)
            self._procs[key] = proc
        self._stop_proc(old_proc)
        return proc

    def stop(self, key: str, timeout: float = 5.0) -> int | None:
        """停止指定 key 的子进程，返回 exit code 或 None。"""
        with self._lock:
            proc = self._procs.pop(key, None)
        return self._stop_proc(proc, timeout=timeout)

    @staticmethod
    def _stop_proc(proc: subprocess.Popen | None, timeout: float = 5.0) -> int | None:
        if proc is None:
            return None
        if proc.poll() is not None:
            return proc.returncode
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return proc.returncode

    def poll(self, key: str) -> int | None:
        """检查指定 key 的进程是否仍在运行。"""
        with self._lock:
            proc = self._procs.get(key)
        if proc is None:
            return None
        return proc.poll()

    @staticmethod
    def _resolve_cmd(cmd: list[str]) -> list[str]:
        _cmd = list(cmd)
        if _cmd and _cmd[0] == "adb":
            _cmd[0] = adb_path()
        return _cmd

    @property
    def active_keys(self) -> list[str]:
        with self._lock:
            return [k for k, p in self._procs.items() if p.poll() is None]

    def stop_all(self):
        with self._lock:
            keys = list(self._procs.keys())
        for key in keys:
            self.stop(key)
