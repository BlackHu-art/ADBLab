"""提供短生命周期命令统一的 subprocess.run 执行入口。"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from time import perf_counter

CF = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_adb_path: str | None = None
_active_commands = 0
_active_lock = threading.Lock()


def _get_adb_path() -> str:
    """解析并缓存 ADB 可执行文件路径。"""
    global _adb_path
    if _adb_path is None:
        from utils.adb_resolver import adb_path
        _adb_path = adb_path()
    return _adb_path


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
        resolved_cmd = _resolve_cmd(cmd)
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
        resolved_cmd = _resolve_cmd(cmd)
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


def _resolve_cmd(cmd: list[str]) -> list[str]:
    resolved = list(cmd)
    if resolved and resolved[0] == "adb":
        resolved[0] = _get_adb_path()
    return resolved


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

        value = AppSettings.instance().get("performance_log_threshold_ms", DEFAULT_SLOW_THRESHOLD_MS)
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
    shell_parts = parts[index + 1:]
    if not shell_parts:
        return "adb shell"
    first = shell_parts[0]
    if first == "sh":
        return "adb shell sh"
    if first in {"cmd", "dumpsys", "pm", "am", "input", "getprop", "settings", "monkey"}:
        second = shell_parts[1] if len(shell_parts) > 1 else ""
        return f"adb shell {first}{(' ' + second) if second else ''}"
    return f"adb shell {first}"
