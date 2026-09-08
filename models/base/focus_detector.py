"""通过多种 Android 系统输出尽力识别设备当前前台应用。"""

import re
from collections.abc import Callable
from time import monotonic
from typing import Protocol

from core.exec import CommandResult, CommandRunner

_PACKAGE_RE = re.compile(r"([\w.]+(?:\.[\w.]+)+)/")
_TOP_ACTIVITY_RE = re.compile(r"topActivity=ComponentInfo\{([\w.]+(?:\.[\w.]+)+)/")


class CommandRunnerLike(Protocol):
    """前台包探测所需的最小命令执行接口。"""

    def run(
        self,
        command: list[str],
        /,
        timeout: float = 30,
    ) -> CommandResult: ...


def extract_package_name(output: str) -> str:
    """从 activity/window 输出中提取首个可信的前台包名。"""
    lines = output.splitlines()
    for line in lines:
        if "visible=true" not in line or "topActivity=ComponentInfo" not in line:
            continue
        match = _TOP_ACTIVITY_RE.search(line)
        if match:
            return match.group(1)
    focused_lines = [
        line
        for line in lines
        if any(
            token in line
            for token in ("mCurrentFocus", "mFocusedApp", "mResumedActivity", "topResumedActivity")
        )
    ]
    for line in focused_lines + lines:
        if "/" not in line:
            continue
        match = _PACKAGE_RE.search(line)
        if match:
            return match.group(1)
    return ""


def detect_current_package(
    device_ip: str,
    runner: CommandRunnerLike = CommandRunner,
    *, timeout: float = 15, cancelled: Callable[[], bool] | None = None,
) -> dict:
    """兼容探测共享总预算；默认执行器支持在途取消，自定义执行器负责传递停止意图。"""
    deadline = monotonic() + max(0, timeout)
    commands = [
        ["adb", "-s", device_ip, "shell", "cmd", "activity", "stack", "list"],
        [
            "adb",
            "-s",
            device_ip,
            "shell",
            "sh",
            "-c",
            "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
        ],
        ["adb", "-s", device_ip, "shell", "dumpsys", "activity", "top"],
    ]
    for command in commands:
        remaining = deadline - monotonic()
        if remaining <= 0 or (cancelled is not None and cancelled()):
            break
        if runner is CommandRunner and cancelled is not None:
            result = CommandRunner.run(command, timeout=min(5, remaining), cancelled=cancelled)
        else:
            result = runner.run(command, timeout=min(5, remaining))
        if cancelled is not None and cancelled():
            break
        if not result.success:
            continue
        package_name = extract_package_name(result.output)
        if package_name:
            return {"success": True, "device_ip": device_ip, "package_name": package_name}
    return {"success": False, "device_ip": device_ip, "error": "No focus info found"}
