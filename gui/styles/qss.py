"""ADBLab QSS stylesheet templates."""

from .theme import _tc
from .fonts import _font

RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8
RADIUS_XL = 12


class QSSMixin:
    """Add to BaseStyles via inheritance for all QSS template methods."""

    # -- Scrollbar -------------------------------------------------------

    @classmethod
    def SCROLLBAR_STYLE(cls) -> str:
        h = _tc("SCROLLBAR_HANDLE")
        hh = _tc("SCROLLBAR_HANDLE_HOVER")
        return f"""
        QScrollBar {{
            background: transparent; border: none;
        }}
        QScrollBar:vertical {{ width: 8px; padding: 2px 1px; }}
        QScrollBar:horizontal {{ height: 8px; padding: 1px 2px; }}
        QScrollBar::handle:vertical {{
            background: {h}; min-height: 30px; border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {h}; min-width: 30px; border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover,
        QScrollBar::handle:horizontal:hover {{ background: {hh}; }}
        QScrollBar::handle:vertical:pressed,
        QScrollBar::handle:horizontal:pressed {{ background: {_tc('BORDER_FOCUS')}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0; width: 0; border: none; background: none;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QScrollBar::corner {{ background: transparent; }}
        """

    # -- Buttons ---------------------------------------------------------

    @classmethod
    def BUTTON_BASE(cls) -> str:
        return f"""
            font-family: '{_font['FAMILY']}'; font-size: {_font['UI']}px;
            border-radius: {RADIUS_MD}px; padding: 3px 8px;
        """

    @classmethod
    def BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton {{
            {cls.BUTTON_BASE()}
            background-color: {_tc('BUTTON_BG')}; color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')};
        }}
        QPushButton:hover {{
            background-color: {_tc('BUTTON_HOVER')}; border-color: {_tc('BORDER_FOCUS')};
        }}
        QPushButton:pressed {{ background-color: {_tc('BUTTON_PRESSED')}; }}
        QPushButton:disabled {{
            background-color: {_tc('INPUT_BG')}; color: {_tc('TEXT_DISABLED')};
            border-color: {_tc('BORDER_COLOR')};
        }}
        """

    @classmethod
    def ACCENT_BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton#accent {{
            {cls.BUTTON_BASE()}
            background-color: {_tc('BUTTON_ACCENT')}; color: #ffffff;
            border: 1px solid {_tc('BUTTON_ACCENT')};
        }}
        QPushButton#accent:hover {{ background-color: {_tc('BUTTON_ACCENT_HOVER')}; }}
        QPushButton#accent:pressed {{ background-color: {_tc('BUTTON_ACCENT_PRESSED')}; }}
        QPushButton#accent:disabled {{
            background-color: {_tc('INPUT_BG')}; color: {_tc('TEXT_DISABLED')};
            border-color: {_tc('BORDER_COLOR')};
        }}
        """

    @classmethod
    def DANGER_BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton#danger {{
            {cls.BUTTON_BASE()}
            background-color: {_tc('BUTTON_DANGER')}; color: #ffffff;
            border: 1px solid {_tc('BUTTON_DANGER')};
        }}
        QPushButton#danger:hover {{ background-color: {_tc('BUTTON_DANGER_HOVER')}; }}
        QPushButton#danger:pressed {{ background-color: {_tc('BUTTON_DANGER')}; }}
        QPushButton#danger:disabled {{
            background-color: {_tc('INPUT_BG')}; color: {_tc('TEXT_DISABLED')};
            border-color: {_tc('BORDER_COLOR')};
        }}
        """

    @classmethod
    def BUTTON_QSS(cls) -> str:
        return cls.BUTTON_STYLE() + cls.ACCENT_BUTTON_STYLE() + cls.DANGER_BUTTON_STYLE()

    # -- Input -----------------------------------------------------------

    @classmethod
    def INPUT_STYLE(cls) -> str:
        return f"""
        QLineEdit, QComboBox {{
            background-color: {_tc('INPUT_BG')}; color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')}; border-radius: {RADIUS_MD}px;
            padding: 3px 6px; font-family: '{_font['FAMILY']}';
            font-size: {_font['UI']}px; selection-background-color: {_tc('SELECTION_BG')};
        }}
        QLineEdit:focus, QComboBox:focus {{ border-color: {_tc('BORDER_FOCUS')}; }}
        QLineEdit:disabled, QComboBox:disabled {{
            background-color: {_tc('PANEL_BG')}; color: {_tc('TEXT_DISABLED')};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right; width: 20px;
            border-left: 1px solid {_tc('BORDER_COLOR')};
            border-top-right-radius: {RADIUS_MD}px; border-bottom-right-radius: {RADIUS_MD}px;
            background-color: {_tc('BUTTON_BG')};
        }}
        QComboBox::drop-down:hover {{ background-color: {_tc('BUTTON_HOVER')}; }}
        QComboBox::down-arrow {{
            image: url(icons:dropdown_arrow.svg); width: 10px; height: 6px; margin-right: 4px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {_tc('INPUT_BG')}; color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')}; border-radius: {RADIUS_SM}px;
            selection-background-color: {_tc('SELECTION_BG')};
            selection-color: {_tc('SELECTION_TEXT')}; outline: none;
            font-family: 'Courier New', monospace;
        }}
        QComboBox QAbstractItemView::item {{ color: {_tc('TEXT_PRIMARY')}; padding: 4px 8px; }}
        QComboBox QAbstractItemView::item:selected {{
            background-color: {_tc('SELECTION_BG')}; color: {_tc('SELECTION_TEXT')};
        }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {_tc('BUTTON_HOVER')}; color: {_tc('TEXT_PRIMARY')};
        }}
        """

    # -- Group Box -------------------------------------------------------

    @classmethod
    def GROUP_BOX_STYLE(cls) -> str:
        return f"""
        QGroupBox {{
            background-color: {_tc('PANEL_BG')}; border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_LG}px; margin-top: 4px; padding: 2px 4px 1px 4px;
            font-family: '{_font['FAMILY']}'; font-size: {_font['UI']}px;
            font-weight: bold; color: {_tc('TEXT_PRIMARY')};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px;
            left: 10px; color: {_tc('GROUP_TITLE_COLOR')};
        }}
        """

    # -- List Widget -----------------------------------------------------

    @classmethod
    def LIST_WIDGET_STYLE(cls) -> str:
        return f"""
        QListWidget {{
            background-color: {_tc('INPUT_BG')}; color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')}; border-radius: {RADIUS_MD}px;
            padding: 2px; font-family: 'Courier New'; font-size: {_font['UI']}px;
            outline: none;
        }}
        QListWidget::item {{ padding: 3px 6px; border-radius: {RADIUS_SM}px; color: {_tc('TEXT_PRIMARY')}; }}
        QListWidget::item:selected {{
            background-color: {_tc('SELECTION_BG')}; color: {_tc('SELECTION_TEXT')};
        }}
        QListWidget::item:hover {{ background-color: {_tc('BUTTON_HOVER')}; }}
        """

    # -- Toolbar ---------------------------------------------------------

    @classmethod
    def TOOLBAR_STYLE(cls) -> str:
        return f"""
        QFrame#toolbar {{
            background-color: {_tc('TOOLBAR_BG')}; border-radius: {RADIUS_MD}px;
            border: 1px solid {_tc('BORDER_COLOR')};
        }}
        QFrame#toolbar QPushButton {{
            background-color: transparent; color: {_tc('TEXT_PRIMARY')};
            border: none; border-radius: {RADIUS_SM}px; padding: 2px 6px;
            font-family: '{_font['FAMILY']}'; font-size: {_font['UI']}px;
        }}
        QFrame#toolbar QPushButton:hover {{ background-color: {_tc('BUTTON_HOVER')}; }}
        QFrame#toolbar QPushButton#exit_btn:hover {{
            background-color: {_tc('BUTTON_DANGER')}; color: #ffffff;
        }}
        QFrame#toolbar QLabel {{
            color: {_tc('TEXT_PRIMARY')}; font-family: '{_font['FAMILY']}';
            font-size: {_font['UI']}px; font-weight: bold;
        }}
        """

    # -- Composite: PANEL_BASE_STYLE -------------------------------------

    @classmethod
    def PANEL_BASE_STYLE(cls) -> str:
        return (
            cls.BUTTON_QSS()
            + cls.INPUT_STYLE()
            + cls.LIST_WIDGET_STYLE()
            + f"QWidget {{ background-color: {_tc('WINDOW_BG')}; color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QFrame {{ background-color: transparent; border: none; color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QLabel {{ color: {_tc('TEXT_PRIMARY')}; background-color: transparent; }}"
            + f"QCheckBox {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QStatusBar {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QTableWidget {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QHeaderView::section {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + cls.SCROLLBAR_STYLE()
        )
