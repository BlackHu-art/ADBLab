"""应用管理功能入口；协作者可独立加载，页面在访问公开名时才导入。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .details import AppDetailsPage as AppDetailsPage
    from .page import AppManagerPage as AppManagerPage
    from .page import AppSortProxy as AppSortProxy

__all__ = ["AppDetailsPage", "AppManagerPage", "AppSortProxy"]


def __getattr__(name: str):
    """按原公开名称延迟导入页面，避免协作者导入触发完整页面依赖。"""
    if name == "AppDetailsPage":
        from .details import AppDetailsPage

        return AppDetailsPage
    if name == "AppManagerPage":
        from .page import AppManagerPage

        return AppManagerPage
    if name == "AppSortProxy":
        from .page import AppSortProxy

        return AppSortProxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
