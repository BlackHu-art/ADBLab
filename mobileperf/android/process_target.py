"""统一性能采集进程名的安全边界与跨平台文件身份。"""

import re

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9_.]+")


def is_safe_process_name(value: str) -> bool:
    """允许包名及单个冒号分隔的子进程名，拒绝路径和 shell 元字符。"""
    parts = value.split(":")
    return len(parts) <= 2 and all(
        _SAFE_COMPONENT.fullmatch(part) is not None
        and not part.startswith(".") and ".." not in part
        for part in parts
    )


def process_file_segment(process: str) -> str:
    """保留主进程旧文件名；编码子进程的冒号和大写字母以兼容大小写不敏感文件系统。

    百分号不在合法输入内，编码可逆且不会与普通主进程名或其他子进程混淆。
    """
    if not is_safe_process_name(process):
        raise ValueError("无效的性能采集进程名。")
    if ":" not in process:
        return process
    return "".join(f"%{ord(char):02X}" if char == ":" or char.isupper() else char
                   for char in process)
