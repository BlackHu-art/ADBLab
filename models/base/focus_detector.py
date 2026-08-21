"""通过多种 Android 系统输出尽力识别设备当前前台应用。"""

import re

from core.exec import CommandRunner

_PACKAGE_RE = re.compile(r"([\w.]+(?:\.[\w.]+)+)/")
_TOP_ACTIVITY_RE = re.compile(r"topActivity=ComponentInfo\{([\w.]+(?:\.[\w.]+)+)/")


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


def detect_current_package(device_ip: str, runner=CommandRunner) -> dict:
    """依次执行兼容性探测命令，任一命令识别成功即返回前台包名。"""
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
        result = runner.run(command, timeout=5)
        if not result.success:
            continue
        package_name = extract_package_name(result.output)
        if package_name:
            return {"success": True, "device_ip": device_ip, "package_name": package_name}
    return {"success": False, "device_ip": device_ip, "error": "No focus info found"}
