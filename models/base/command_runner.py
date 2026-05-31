"""
全项目唯一 subprocess.run 入口。

所有命令执行统一经过 CommandRunner.run()，返回标准化的 CommandResult。
"""

import subprocess
import sys
from dataclasses import dataclass

CF = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 模块级缓存 adb 路径，避免每次 subprocess 触发 Windows PATH 搜索
_adb_path: str | None = None


def _get_adb_path() -> str:
    """Return resolved adb path, with module-level cache."""
    global _adb_path
    if _adb_path is None:
        from utils.adb_resolver import adb_path
        _adb_path = adb_path()
    return _adb_path


@dataclass
class CommandResult:
    """统一命令执行结果。"""
    success: bool
    output: str = ""
    error: str = ""
    returncode: int = 0

    @property
    def stdout(self) -> str:
        """兼容旧代码的 stdout 别名。"""
        return self.output


class CommandRunner:
    """唯一 subprocess.run 入口 —— 全项目所有同步命令执行经由此处。"""

    @staticmethod
    def run(cmd: list[str], timeout: int = 30, shell: bool = False) -> CommandResult:
        # 解析 adb 路径，消除 Windows CreateProcess 的 PATH 搜索开销
        _cmd = list(cmd)
        if _cmd and _cmd[0] == "adb":
            _cmd[0] = _get_adb_path()
        try:
            r = subprocess.run(
                _cmd,
                capture_output=True,
                text=True,
                shell=shell,
                timeout=timeout,
                encoding="utf-8",
                errors="ignore",
                creationflags=CF,
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout).strip()
                return CommandResult(success=False, returncode=r.returncode, error=err)
            return CommandResult(success=True, output=r.stdout.strip(), returncode=0)
        except subprocess.TimeoutExpired:
            return CommandResult(success=False, error=f"Timeout({timeout}s)")
        except Exception as e:
            return CommandResult(success=False, error=str(e))

    @staticmethod
    def run_to_file(
        cmd: list[str],
        output_path: str,
        timeout: int = 30,
        shell: bool = False,
    ) -> CommandResult:
        """Run a command and stream binary stdout directly to a file."""
        _cmd = list(cmd)
        if _cmd and _cmd[0] == "adb":
            _cmd[0] = _get_adb_path()
        try:
            with open(output_path, "wb") as output_file:
                r = subprocess.run(
                    _cmd,
                    stdout=output_file,
                    stderr=subprocess.PIPE,
                    shell=shell,
                    timeout=timeout,
                    creationflags=CF,
                )
            if r.returncode != 0:
                err = (r.stderr or b"").decode("utf-8", errors="ignore").strip()
                return CommandResult(success=False, returncode=r.returncode, error=err)
            return CommandResult(success=True, output=output_path, returncode=0)
        except subprocess.TimeoutExpired:
            return CommandResult(success=False, error=f"Timeout({timeout}s)")
        except Exception as e:
            return CommandResult(success=False, error=str(e))
