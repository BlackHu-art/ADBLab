from PySide6.QtGui import QFont

class Styles:
    DEFAULT_FONT_SIZE = 10
    LOG_FONT_SIZE = 10
    LOG_FONT = "Consolas"
    INFO_COLOR = "#00FF00"
    WARNING_COLOR = "#FFA500"
    ERROR_COLOR = "#FF0000"
    LOG_BACKGROUND = "#000000"
    LOG_TEXT_COLOR = "#FFFFFF"
    WINDOW_BACKGROUND = "#f0f0f0"

def get_default_font():
    return QFont("Segoe UI", Styles.DEFAULT_FONT_SIZE)
