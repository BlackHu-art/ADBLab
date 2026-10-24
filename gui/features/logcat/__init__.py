"""实时 Logcat 功能包；按需加载页面，允许独立导入工作线程。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .page import LiveLogcatPage

__all__ = ["LiveLogcatPage"]


def __getattr__(name: str):
    """保留页面公开入口，并避免工作线程导入触发页面循环。"""
    if name == "LiveLogcatPage":
        from .page import LiveLogcatPage

        return LiveLogcatPage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
