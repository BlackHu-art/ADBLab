"""汇总资源路径与 ADB 解析等通用工具。"""

from utils.adb_resolver import adb_path, is_adb_available
from utils.resource_path import resource_path, setup_qt_search_paths

__all__ = [
    "resource_path",
    "setup_qt_search_paths",
    "adb_path",
    "is_adb_available",
]
