"""汇总资源路径与 ADB 解析等通用工具。"""

from utils.resource_path import resource_path, setup_qt_search_paths


def adb_path() -> str:
    """保留包级解析入口；仅实际请求 ADB 时加载解析器，避免拖慢纯资源和启动画面。"""
    from utils.adb_resolver import adb_path as resolve_adb_path

    return resolve_adb_path()


__all__ = [
    "resource_path",
    "setup_qt_search_paths",
    "adb_path",
]
