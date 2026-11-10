"""加载应用图标，仅依赖 Qt 与资源解析，可在启动首帧前安全使用。"""

from PySide6.QtGui import QIcon

from utils.resource_path import resource_path


def load_app_icon() -> QIcon:
    """优先保留高分辨率 PNG，资源缺失或解码失败时回退到原有 ICO。"""
    icon = QIcon(resource_path("resources/app-icon.png"))
    if icon.isNull():
        return QIcon(resource_path("icon.ico"))
    return icon
