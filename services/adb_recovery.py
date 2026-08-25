"""ADB Server 的受限恢复服务。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.exec import CommandRunner
from core.process_utils import find_pids_listening_on, kill_process_tree, process_executable
from utils.adb_resolver import adb_path

ADB_SERVER_PORT = 5037


@dataclass(frozen=True)
class AdbRecoveryResult:
    """描述恢复是否成功，以及是否使用了进程级兜底终止。"""

    success: bool
    detail: str
    forced: bool = False


def recover_adb_server() -> AdbRecoveryResult:
    """重启项目解析到的 ADB Server，不终止其他工具提供的 5037 监听进程。

    先请求 ``adb kill-server`` 正常退出；协议已卡死时，只允许终止可执行路径与项目
    当前 ADB 完全一致的监听进程，避免误伤 Android Studio 或其他外部 ADB 实例。
    """

    executable = adb_path()
    graceful = CommandRunner.run([executable, "kill-server"], timeout=3)
    forced = False
    if not graceful.success:
        listeners = find_pids_listening_on(ADB_SERVER_PORT)
        matching = [
            pid
            for pid in listeners
            if _same_executable(process_executable(pid), executable)
        ]
        if listeners and not matching:
            return AdbRecoveryResult(False, "foreign-listener")
        for pid in matching:
            stopped, _detail = kill_process_tree(pid, timeout=2.0)
            if not stopped:
                return AdbRecoveryResult(False, "listener-stop-failed", forced=True)
            forced = True

    started = CommandRunner.run([executable, "start-server"], timeout=5)
    if not started.success:
        return AdbRecoveryResult(False, "start-failed", forced=forced)
    return AdbRecoveryResult(True, "forced-restart" if forced else "graceful-restart", forced)


def _same_executable(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return os.path.normcase(os.path.realpath(candidate)) == os.path.normcase(
        os.path.realpath(expected)
    )
