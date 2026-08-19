"""统一管理 monkey、logcat、录屏和 scrcpy 等长生命周期子进程。

``start`` 创建的进程会进入实例和全局跟踪表，``spawn`` 则把清理责任交给调用方。
隔离运行的 MobilePerf 子进程仍通过其适配器调用本模块，不要求采集内核直接依赖此处。
"""

import subprocess
import sys
import threading
import time

from utils.adb_resolver import adb_path

from .command_runner import CF

CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
        stdin=None,
        cwd: str | None = None,
        text: bool = False,
        encoding: str | None = None,
        errors: str | None = None,
        bufsize: int = -1,
        creationflags: int | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """启动子进程，同名 key 会先停止旧进程。"""
        with self._lock:
            old_proc = self._procs.pop(key, None)
        self._unregister_global(key, old_proc)
        self._stop_proc(old_proc)

        proc = self.spawn(
            cmd,
            stdout=subprocess.DEVNULL if stdout is None else stdout,
            stderr=subprocess.DEVNULL if stderr is None else stderr,
            stdin=stdin,
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
        self._stop_proc(old_proc)
        self._register_global(key, proc)
        return proc

    def spawn(
        self,
        cmd: list[str],
        stdout=None,
        stderr=None,
        *,
        stdin=None,
        cwd: str | None = None,
        text: bool = False,
        encoding: str | None = None,
        errors: str | None = None,
        bufsize: int = -1,
        creationflags: int | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """启动不进入活动进程表的子进程，调用方必须自行管理其生命周期。"""
        popen_kwargs = {
            "creationflags": CF if creationflags is None else creationflags,
            "cwd": cwd,
            "text": text,
            "bufsize": bufsize,
        }
        if stdin is not None:
            popen_kwargs["stdin"] = stdin
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
            proc = self._procs.get(key)
        code = self._stop_proc(proc, timeout=timeout)
        if proc is None:
            return code
        try:
            stopped = proc.poll() is not None or code is not None
        except Exception:
            stopped = code is not None
        if stopped:
            with self._lock:
                if self._procs.get(key) is proc:
                    self._procs.pop(key, None)
            self._unregister_global(key, proc)
        return code

    def request_stop(self, key: str) -> bool:
        """请求进程正常终止，但不等待退出，也不提前移除跟踪记录。"""
        with self._lock:
            proc = self._procs.get(key)
        if proc is None:
            return False
        try:
            if proc.poll() is not None:
                return False
            proc.terminate()
            return True
        except OSError:
            return False

    def force_stop(self, key: str, timeout: float = 2.0) -> bool:
        """在调用方给定的总时限内强制停止一个被跟踪进程。"""
        with self._lock:
            proc = self._procs.get(key)
        if proc is None:
            return False
        try:
            if proc.poll() is not None:
                self.stop(key, timeout=0)
                return False
        except OSError:
            return False

        deadline = time.monotonic() + max(0.0, float(timeout))
        attempted = self._kill_process_tree_bounded(proc, deadline)
        if not attempted:
            try:
                proc.kill()
                attempted = True
            except OSError:
                pass
        remaining = max(0.0, deadline - time.monotonic())
        if remaining:
            try:
                proc.wait(timeout=remaining)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            stopped = proc.poll() is not None
        except OSError:
            stopped = False
        if stopped:
            with self._lock:
                if self._procs.get(key) is proc:
                    self._procs.pop(key, None)
            self._unregister_global(key, proc)
        return attempted

    @staticmethod
    def _kill_process_tree_bounded(proc: subprocess.Popen, deadline: float) -> bool:
        """在 Windows 上按绝对截止时间调用 taskkill 终止进程树。"""
        if sys.platform != "win32":
            return False
        pid = getattr(proc, "pid", None)
        if not pid:
            return False
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return False
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=remaining,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _stop_proc(proc: subprocess.Popen | None, timeout: float = 5.0) -> int | None:
        """先请求正常退出，超时后终止进程树并返回可确认的退出码。"""
        if proc is None:
            return None
        try:
            if proc.poll() is not None:
                return proc.returncode
            proc.terminate()
        except OSError:
            return getattr(proc, "returncode", None)
        try:
            proc.wait(timeout=timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            if not ProcessRunner._kill_process_tree(proc):
                try:
                    proc.kill()
                except OSError:
                    return getattr(proc, "returncode", None)
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    return getattr(proc, "returncode", None)
            return proc.returncode
        except OSError:
            return getattr(proc, "returncode", None)

    @staticmethod
    def _kill_process_tree(proc: subprocess.Popen) -> bool:
        """在 Windows 上终止目标进程及其子进程，其他平台返回 False。"""
        if sys.platform != "win32":
            return False
        pid = getattr(proc, "pid", None)
        if not pid:
            return False
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
            return True
        except Exception:
            return False

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
        """停止当前实例跟踪的所有进程。"""
        with self._lock:
            keys = list(self._procs.keys())
        for key in keys:
            self.stop(key)

    @classmethod
    def stop_all_tracked(cls):
        """兜底停止所有由 ``start`` 管理的进程；``spawn`` 创建的进程不纳入。"""
        with cls._global_lock:
            items = list(cls._global_procs.items())
        for proc_key, proc in items:
            try:
                code = cls._stop_proc(proc)
            except Exception:
                code = None
            try:
                stopped = proc.poll() is not None or code is not None
            except Exception:
                stopped = code is not None
            if stopped:
                with cls._global_lock:
                    if cls._global_procs.get(proc_key) is proc:
                        cls._global_procs.pop(proc_key, None)

    @classmethod
    def tracked_active_count(cls) -> int:
        """返回全局跟踪表中仍存活的进程数量，并清理已退出记录。"""
        with cls._global_lock:
            items = list(cls._global_procs.items())
        active = 0
        stopped_items = []
        for proc_key, proc in items:
            try:
                if proc.poll() is None:
                    active += 1
                else:
                    stopped_items.append((proc_key, proc))
            except OSError:
                active += 1
        if stopped_items:
            with cls._global_lock:
                for proc_key, proc in stopped_items:
                    if cls._global_procs.get(proc_key) is proc:
                        cls._global_procs.pop(proc_key, None)
        return active

    @classmethod
    def force_all_tracked(cls, timeout: float) -> bool:
        """在共享截止时间内强制停止所有全局跟踪进程。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with cls._global_lock:
            items = list(cls._global_procs.items())
        attempted = False
        for proc_key, proc in items:
            try:
                if proc.poll() is not None:
                    stopped = True
                else:
                    tree_killed = cls._kill_process_tree_bounded(proc, deadline)
                    if not tree_killed:
                        proc.kill()
                    attempted = True
                    remaining = max(0.0, deadline - time.monotonic())
                    if remaining:
                        try:
                            proc.wait(timeout=remaining)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                    stopped = proc.poll() is not None
            except OSError:
                stopped = False
            if stopped:
                with cls._global_lock:
                    if cls._global_procs.get(proc_key) is proc:
                        cls._global_procs.pop(proc_key, None)
        return attempted

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
