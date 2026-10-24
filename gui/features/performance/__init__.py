"""性能功能包；按需加载页面，允许独立导入结果协作者。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .page import PerformancePage

__all__ = ["PerformancePage"]


def __getattr__(name: str):
    """保留页面公开入口，独立导入协作者不触发页面构造依赖。"""
    if name == "PerformancePage":
        from .page import PerformancePage

        return PerformancePage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
