"""core 层统一执行契约与短命令执行入口（ADR-0005）。

短命令走 :class:`CommandRunner`（同步 subprocess.run → :class:`CommandResult`），
长进程走 :class:`~core.exec.ProcessRunner`（ADR-0005 Step B 迁入，在此之前由
``models/base/process_runner.py`` 的兼容垫片转出）。ADB 可执行路径解析、Windows
创建标志与 :class:`ExecHandle` 进程句柄协议均在此单一维护，core 不再反向依赖
``models``。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

from core.process_utils import kill_process_tree

CF = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_adb_path: str | None = None
_adb_path_lock = threading.Lock()
_active_commands = 0
_active_lock = threading.Lock()


def resolve_adb_program() -> str:
    """解析并缓存 ADB 可执行文件路径（唯一解析入口）。"""

    global _adb_path
    if _adb_path is None:
        from utils.adb_resolver import adb_path

        with _adb_path_lock:
            if _adb_path is None:
                _adb_path = adb_path()
    return _adb_path


def resolve_command(cmd: list[str]) -> list[str]:
    """返回解析后的命令副本：首位 ``"adb"`` token 替换为 ADB 可执行路径。"""

    resolved = list(cmd)
    if resolved and resolved[0] == "adb":
        resolved[0] = resolve_adb_program()
    return resolved


@runtime_checkable
class ExecHandle(Protocol):
    """进程句柄协议：描述 ``subprocess.Popen`` 与测试替身共同满足的结构面。

    ``MobilePerfRunner``、``ScrcpyService``、``ADBInputSession`` 等适配器面向该
    协议做类型标注，不引入额外包装对象（``Popen`` 天然满足协议）。stdio 以
    ``Any`` 承载，保证管道 reader 与持久输入会话可直接访问流对象（ADR-0005）。
    """

    returncode: int | None
    stdin: Any
    stdout: Any
    stderr: Any

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


@dataclass
class CommandResult:
    """统一的命令执行结果。"""

    success: bool
    output: str = ""
    error: str = ""
    returncode: int = 0

    @property
    def stdout(self) -> str:
        """为旧调用方保留 stdout 兼容属性。"""

        return self.output


class CommandRunner:
    """同步短命令的统一 subprocess.run 边界。"""

    @staticmethod
    def active_count() -> int:
        """返回当前仍在执行的同步命令数量。"""

        with _active_lock:
            return _active_commands

    @staticmethod
    def run(cmd: list[str], timeout: int = 30, shell: bool = False) -> CommandResult:
        """执行有超时上限的短命令，并将退出码和输出归一为 ``CommandResult``。"""

        resolved_cmd = resolve_command(cmd)
        started_at = _mark_started()
        result: CommandResult
        try:
            proc = subprocess.run(
                resolved_cmd,
                capture_output=True,
                text=True,
                shell=shell,
                timeout=timeout,
                encoding="utf-8",
                errors="ignore",
                creationflags=CF,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout).strip()
                result = CommandResult(success=False, returncode=proc.returncode, error=err)
            else:
                result = CommandResult(success=True, output=proc.stdout.strip(), returncode=0)
        except subprocess.TimeoutExpired:
            result = CommandResult(success=False, error=f"Timeout({timeout}s)")
        except Exception as exc:
            result = CommandResult(success=False, error=str(exc))
        finally:
            _mark_finished()
        _log_if_slow(cmd, started_at, result, timeout)
        return result

    @staticmethod
    def run_to_file(
        cmd: list[str],
        output_path: str,
        timeout: int = 30,
        shell: bool = False,
    ) -> CommandResult:
        """执行命令并将二进制标准输出直接写入文件。"""

        resolved_cmd = resolve_command(cmd)
        started_at = _mark_started()
        result: CommandResult
        try:
            with open(output_path, "wb") as output_file:
                proc = subprocess.run(
                    resolved_cmd,
                    stdout=output_file,
                    stderr=subprocess.PIPE,
                    shell=shell,
                    timeout=timeout,
                    creationflags=CF,
                )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
                result = CommandResult(success=False, returncode=proc.returncode, error=err)
            else:
                result = CommandResult(success=True, output=output_path, returncode=0)
        except subprocess.TimeoutExpired:
            result = CommandResult(success=False, error=f"Timeout({timeout}s)")
        except Exception as exc:
            result = CommandResult(success=False, error=str(exc))
        finally:
            _mark_finished()
        _log_if_slow(cmd, started_at, result, timeout)
        return result


def _mark_started() -> float:
    global _active_commands
    with _active_lock:
        _active_commands += 1
    return perf_counter()


def _mark_finished() -> None:
    global _active_commands
    with _active_lock:
        _active_commands = max(0, _active_commands - 1)


def _log_if_slow(cmd: list[str], started_at: float, result: CommandResult, timeout: int) -> None:
    elapsed_ms = (perf_counter() - started_at) * 1000.0
    threshold = _slow_threshold_ms()
    if elapsed_ms < threshold:
        return
    try:
        from core.log_service import LogService

        output_len = len(result.output or "")
        error_len = len(result.error or "")
        LogService().log(
            "DEBUG",
            (
                f"[CMD] {_command_summary(cmd)} elapsed={elapsed_ms:.1f}ms "
                f"rc={result.returncode} timeout={timeout}s "
                f"out={output_len}B err={error_len}B"
            ),
        )
    except Exception:
        pass


def _slow_threshold_ms() -> float:
    try:
        from core.perf_trace import DEFAULT_SLOW_THRESHOLD_MS
        from core.settings_manager import AppSettings

        value = AppSettings.instance().get(
            "performance_log_threshold_ms", DEFAULT_SLOW_THRESHOLD_MS
        )
        return max(0.0, float(value))
    except Exception:
        return 300.0


def _command_summary(cmd: list[str]) -> str:
    if not cmd:
        return "empty"
    parts = [str(part) for part in cmd]
    if _is_adb(parts[0]):
        return _adb_summary(parts)
    return _program_name(parts[0])


def _is_adb(program: str) -> bool:
    return _program_name(program).lower() in {"adb", "adb.exe"}


def _program_name(program: str) -> str:
    return program.replace("\\", "/").rsplit("/", 1)[-1]


def _adb_summary(parts: list[str]) -> str:
    index = 1
    if len(parts) > 2 and parts[1] == "-s":
        index = 3
    if index >= len(parts):
        return "adb"
    command = parts[index]
    if command != "shell":
        return f"adb {command}"
    shell_parts = parts[index + 1 :]
    if not shell_parts:
        return "adb shell"
    first = shell_parts[0]
    if first == "sh":
        return "adb shell sh"
    if first in {"cmd", "dumpsys", "pm", "am", "input", "getprop", "settings", "monkey"}:
        second = shell_parts[1] if len(shell_parts) > 1 else ""
        return f"adb shell {first}{(' ' + second) if second else ''}"
    return f"adb shell {first}"


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
        return subprocess.Popen(resolve_command(cmd), **popen_kwargs)

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
        """在共享绝对截止时间内通过 psutil 终止进程树（ADR-0005 Step C）。"""

        pid = getattr(proc, "pid", None)
        if not pid:
            return False
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return False
        try:
            confirmed, _detail = kill_process_tree(int(pid), force=True, timeout=remaining)
            return confirmed
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
        """通过 psutil 终止目标进程及其子进程（ADR-0005 Step C 统一实现）。"""

        pid = getattr(proc, "pid", None)
        if not pid:
            return False
        try:
            confirmed, _detail = kill_process_tree(int(pid), force=True)
            return confirmed
        except Exception:
            return False

    def poll(self, key: str) -> int | None:
        """检查指定 key 的进程是否仍在运行。"""

        with self._lock:
            proc = self._procs.get(key)
        if proc is None:
            return None
        return proc.poll()

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


__all__ = [
    "CF",
    "CREATE_NEW_CONSOLE",
    "CREATE_NO_WINDOW",
    "CommandResult",
    "CommandRunner",
    "ExecHandle",
    "ProcessRunner",
    "resolve_adb_program",
    "resolve_command",
]
