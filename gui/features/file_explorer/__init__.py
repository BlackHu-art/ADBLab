"""文件浏览器功能包；按需加载页面，允许独立导入预览任务。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .page import FileExplorerPage

__all__ = ["FileExplorerPage"]


def __getattr__(name: str):
    """保留页面公开入口，避免协作者导入提前加载页面。"""
    if name == "FileExplorerPage":
        from .page import FileExplorerPage

        return FileExplorerPage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
