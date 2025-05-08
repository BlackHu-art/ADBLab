import sys
from PySide6.QtWidgets import QApplication
from gui.main_frame import MainFrame

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainFrame()
    window.show()
    sys.exit(app.exec())
