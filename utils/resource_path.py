"""资源路径解析工具 — 同时兼容开发环境和 PyInstaller 打包后的运行环境。

核心函数：
- resource_path()          ：返回操作系统原生路径，供 QIcon / QPixmap 使用
- setup_qt_search_paths()  ：注册 Qt 样式表 url() 的搜索前缀（启动时调用一次即可）
"""

import os
import sys


def _base_dir() -> str:
    """返回资源根目录的绝对路径。

    PyInstaller 打包后资源解压到 sys._MEIPASS；开发模式下为项目根目录（utils/ 的上一级）。
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path: str) -> str:
    """将相对路径转为操作系统原生绝对路径。

    适用于 QIcon()、QPixmap() 等接受本地文件路径的 Qt API。
    """
    return os.path.join(_base_dir(), relative_path)


def setup_qt_search_paths() -> None:
    """注册 Qt 资源搜索前缀，使样式表 url() 可使用短别名引用图标。

    调用后，在 QSS 中可以用 `url(icons:xxx.svg)` 替代绝对路径，
    避免 Windows 路径中括号、空格等字符在 CSS url() 中引发解析错误。

    只需在 QApplication 创建后、窗口初始化前调用一次。
    """
    from PySide6.QtCore import QDir

    QDir.setSearchPaths("icons", [resource_path("resources/icons")])
