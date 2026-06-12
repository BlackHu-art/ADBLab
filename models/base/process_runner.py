"""
统一管理长生命周期子进程：monkey / logcat / 录屏 / scrcpy 等。

全项目所有 subprocess.Popen 入口集中在此。
"""

import subprocess
import threading

from utils.adb_resolver import adb_path

from .command_runner import CF

CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


class ProcessRunner:
    """统一管理后台子进程，支持按 key 启动/停止/轮询。

    用法:
        self._procs = ProcessRunner()
        proc = self._procs.start("logcat_192.168.1.1", ["adb", "logcat"], stdout=fh)
        ...
        self._procs.stop("logcat_192.168.1.1")
    """

    _global_procs: dict[tuple[int, str], subprocess.Popen] = {}
    _global_lock = threading.Lock()

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(
        self,
        key: str,
        cmd: list[str],
        stdout=None,
        stderr=None,
        *,
        cwd: str | None = None,
        text: bool = False,
        encoding: str | None = None,
        errors: str | None = None,
        bufsize: int = -1,
        creationflags: int | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """启动子进程，同名 key 会先停止旧进程。"""
        proc = self.spawn(
            cmd,
            stdout=subprocess.DEVNULL if stdout is None else stdout,
            stderr=subprocess.DEVNULL if stderr is None else stderr,
            cwd=cwd,
            text=text,
            encoding=encoding,
            errors=errors,
            bufsize=bufsize,
            creationflags=creationflags,
            env=env,
        )
        with self._lock:
            old_proc = self._procs.pop(key, None)
            self._procs[key] = proc
        self._unregister_global(key, old_proc)
        self._register_global(key, proc)
        self._stop_proc(old_proc)
        return proc

    def spawn(
        self,
        cmd: list[str],
        stdout=None,
        stderr=None,
        *,
        cwd: str | None = None,
        text: bool = False,
        encoding: str | None = None,
        errors: str | None = None,
        bufsize: int = -1,
        creationflags: int | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """Launch a subprocess without tracking it in the active process map."""
        popen_kwargs = {
            "creationflags": CF if creationflags is None else creationflags,
            "cwd": cwd,
            "text": text,
            "bufsize": bufsize,
        }
        if stdout is not None:
            popen_kwargs["stdout"] = stdout
        if stderr is not None:
            popen_kwargs["stderr"] = stderr
        if encoding is not None:
            popen_kwargs["encoding"] = encoding
        if errors is not None:
            popen_kwargs["errors"] = errors
        if env is not None:
            popen_kwargs["env"] = env
        return subprocess.Popen(self._resolve_cmd(cmd), **popen_kwargs)

    def stop(self, key: str, timeout: float = 5.0) -> int | None:
        """停止指定 key 的子进程，返回 exit code 或 None。"""
        with self._lock:
            proc = self._procs.pop(key, None)
        self._unregister_global(key, proc)
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

    @classmethod
    def stop_all_tracked(cls):
        """兜底停止所有被 ProcessRunner.start() 管理的进程；spawn() 外部启动不纳入。"""
        with cls._global_lock:
            items = list(cls._global_procs.items())
            cls._global_procs.clear()
        for (_owner, _key), proc in items:
            cls._stop_proc(proc)

    def _register_global(self, key: str, proc: subprocess.Popen | None):
        if proc is None:
            return
        with self._global_lock:
            self._global_procs[(id(self), key)] = proc

    def _unregister_global(self, key: str, proc: subprocess.Popen | None):
        if proc is None:
            return
        with self._global_lock:
            stored = self._global_procs.get((id(self), key))
            if stored is proc:
                self._global_procs.pop((id(self), key), None)
