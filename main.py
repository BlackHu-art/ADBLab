import sys
from PySide6.QtWidgets import QApplication
from gui.main_frame import MainFrame
from utils.resource_path import setup_qt_search_paths

if __name__ == '__main__':
    app = QApplication(sys.argv)
    setup_qt_search_paths()
    window = MainFrame()
    window.show()
    sys.exit(app.exec())
