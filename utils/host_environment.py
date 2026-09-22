"""只读识别界面使用的宿主系统名称，不参与 ADB 客户端或执行后端选择。"""

from __future__ import annotations

import platform


def host_system_name() -> str:
    """返回宿主系统显示名；发行版信息不可读时保留 Linux 通用名称。"""

    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system != "Linux":
        return system
    try:
        release = platform.freedesktop_os_release()
    except (OSError, UnicodeError):
        return "Linux"
    # ID_LIKE 只说明发行版渊源，不能把 Ubuntu 衍生系统误报为 Ubuntu。
    return "Ubuntu" if release.get("ID") == "ubuntu" else "Linux"
