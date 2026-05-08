import sys

from PySide6.QtWidgets import QApplication

from gui.main_frame import MainFrame
from gui.styles.base_styles import BaseStyles
from utils.resource_path import setup_qt_search_paths

if __name__ == "__main__":
    app = QApplication(sys.argv)
    setup_qt_search_paths()

    # 在创建窗口前应用已保存的主题，避免 Dark 模式下启动白屏闪烁
    from core.settings_manager import AppSettings

    saved_theme = AppSettings.instance().get("theme", "Light")
    BaseStyles.switch_theme(saved_theme)

    window = MainFrame()
    window.show()
    sys.exit(app.exec())
