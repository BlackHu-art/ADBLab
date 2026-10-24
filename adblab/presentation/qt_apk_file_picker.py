"""以 Qt 文件框实现 APK 选择，不拥有业务状态或后台资源。"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QFileDialog, QWidget


class QtApkFilePicker:
    """仅在 GUI 主线程同步选择；构造不创建控件，异常沿原调用栈传播。"""

    def __init__(self, parent_provider: Callable[[], QWidget | None]) -> None:
        """保存父窗口提供者，选择时再解析，以兼容构造后设置窗口归属。"""
        self._parent_provider = parent_provider

    def select_one(self) -> str | None:
        """保留所选路径原文；取消时返回 None，校验由业务入口承担。"""
        path, _ = QFileDialog.getOpenFileName(
            self._parent_provider(),
            QCoreApplication.translate("ADBLab", "Select APK File"),
            "",
            QCoreApplication.translate("ADBLab", "APK Files (*.apk);;All Files (*)"),
        )
        return path or None

    def select_many(self) -> tuple[str, ...]:
        """按文件框原顺序返回路径，保留重复项；取消时返回空元组。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self._parent_provider(),
            QCoreApplication.translate("ADBLab", "Select APK files to install"),
            "",
            QCoreApplication.translate("ADBLab", "APK Files (*.apk);;All Files (*)"),
        )
        return tuple(paths)
