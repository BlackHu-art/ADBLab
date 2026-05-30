import ctypes
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.main_frame import MainFrame
from gui.styles import BaseStyles
from utils.app_metadata import app_major_minor_version
from utils.resource_path import resource_path, setup_qt_search_paths


def windows_app_user_model_id() -> str:
    return f"ADBLab.Frankie.{app_major_minor_version()}"


if __name__ == "__main__":
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(windows_app_user_model_id())

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    setup_qt_search_paths()

    # 在创建窗口前应用已保存的主题，避免 Dark 模式下启动白屏闪烁
    from core.settings_manager import AppSettings

    BaseStyles.reload_from_settings()
    saved_theme = AppSettings.instance().get("theme", "Light")
    BaseStyles.switch_theme(saved_theme)

    window = MainFrame()
    window.show()
    sys.exit(app.exec())
