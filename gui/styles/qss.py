"""提供 ADBLab 控件使用的 QSS 样式模板。"""

from typing import Any, cast

from PySide6.QtGui import QFontMetrics

from .theme import _tc
from .typography import FontRole

RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8
RADIUS_XL = 12


class QSSMixin:
    """通过 BaseStyles 提供全部 QSS 模板方法。"""

    # ── 滚动条 ──────────────────────────────────────────────────────────

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
        QScrollBar::handle:horizontal:pressed {{ background: {_tc("BORDER_FOCUS")}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0; width: 0; border: none; background: none;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QScrollBar::corner {{ background: transparent; }}
        """

    # ── 按钮 ────────────────────────────────────────────────────────────

    @classmethod
    def BUTTON_BASE(cls) -> str:
        return f"""
            border-radius: {RADIUS_MD}px; padding: 3px 8px;
        """

    @classmethod
    def BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton {{
            {cls.BUTTON_BASE()}
            background-color: {_tc("BUTTON_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")};
        }}
        QPushButton:hover {{
            background-color: {_tc("BUTTON_HOVER")}; border-color: {_tc("BORDER_FOCUS")};
        }}
        QPushButton:pressed {{ background-color: {_tc("BUTTON_PRESSED")}; }}
        QPushButton:focus {{ border: 2px solid {_tc("BORDER_FOCUS")}; }}
        QPushButton:disabled {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_DISABLED")};
            border-color: {_tc("BORDER_COLOR")};
        }}
        """

    @classmethod
    def ACCENT_BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton#accent {{
            {cls.BUTTON_BASE()}
            background-color: {_tc("BUTTON_ACCENT")}; color: #ffffff;
            border: 1px solid {_tc("BUTTON_ACCENT")};
        }}
        QPushButton#accent:hover {{ background-color: {_tc("BUTTON_ACCENT_HOVER")}; }}
        QPushButton#accent:pressed {{ background-color: {_tc("BUTTON_ACCENT_PRESSED")}; }}
        QPushButton#accent:focus {{ border: 2px solid {_tc("TEXT_PRIMARY")}; }}
        QPushButton#accent:disabled {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_DISABLED")};
            border-color: {_tc("BORDER_COLOR")};
        }}
        """

    @classmethod
    def DANGER_BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton#danger {{
            {cls.BUTTON_BASE()}
            background-color: {_tc("BUTTON_DANGER")}; color: #ffffff;
            border: 1px solid {_tc("BUTTON_DANGER")};
        }}
        QPushButton#danger:hover {{ background-color: {_tc("BUTTON_DANGER_HOVER")}; }}
        QPushButton#danger:pressed {{ background-color: {_tc("BUTTON_DANGER")}; }}
        QPushButton#danger:focus {{ border: 2px solid {_tc("TEXT_PRIMARY")}; }}
        QPushButton#danger:disabled {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_DISABLED")};
            border-color: {_tc("BORDER_COLOR")};
        }}
        """

    @classmethod
    def BUTTON_QSS(cls) -> str:
        return cls.BUTTON_STYLE() + cls.ACCENT_BUTTON_STYLE() + cls.DANGER_BUTTON_STYLE()

    # ── 输入控件 ────────────────────────────────────────────────────────

    @classmethod
    def INPUT_STYLE(cls) -> str:
        # QSS 加载 SVG 时不会继承控件的前景色，因此使用按主题固化描边色的资源。
        theme_suffix = "dark" if cast(Any, cls).current_theme() == "Dark" else "light"
        arrow_icon = f"caret-down-qss-{theme_suffix}.svg"
        up_arrow_icon = f"caret-up-qss-{theme_suffix}.svg"
        return f"""
        QLineEdit, QComboBox, QSpinBox {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 3px 6px; selection-background-color: {_tc("SELECTION_BG")};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
            border-color: {_tc("BORDER_FOCUS")};
        }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
            background-color: {_tc("PANEL_BG")}; color: {_tc("TEXT_DISABLED")};
        }}
        QSpinBox[inputInvalid="true"], QSpinBox[inputInvalid="true"]:focus {{
            border: 2px solid {_tc("BUTTON_DANGER")};
        }}
        QSpinBox QLineEdit {{
            background-color: transparent; border: none; border-radius: 0;
            padding: 0 4px; color: {_tc("TEXT_PRIMARY")};
        }}
        QSpinBox QLineEdit:disabled {{
            background-color: transparent; color: {_tc("TEXT_DISABLED")};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            subcontrol-origin: border; width: 18px;
            background-color: {_tc("BUTTON_BG")};
            border-left: 1px solid {_tc("BORDER_COLOR")};
        }}
        QSpinBox::up-button {{
            subcontrol-position: top right; border-top-right-radius: {RADIUS_MD}px;
        }}
        QSpinBox::down-button {{
            subcontrol-position: bottom right; border-bottom-right-radius: {RADIUS_MD}px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: {_tc("BUTTON_HOVER")};
        }}
        QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {{
            background-color: {_tc("PANEL_BG")};
            border-left-color: {_tc("BORDER_COLOR")};
        }}
        QSpinBox::up-arrow {{
            image: url(icons:{up_arrow_icon}); width: 12px; height: 8px;
        }}
        QSpinBox::down-arrow {{
            image: url(icons:{arrow_icon}); width: 12px; height: 8px;
        }}
        QSpinBox::up-arrow:disabled {{
            image: url(icons:{up_arrow_icon}); width: 12px; height: 8px;
        }}
        QSpinBox::down-arrow:disabled {{
            image: url(icons:{arrow_icon}); width: 12px; height: 8px;
        }}
        QToolButton#presetMenuButton {{
            background-color: {_tc("BUTTON_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 3px 6px; qproperty-icon: url(icons:{arrow_icon});
        }}
        QToolButton#presetMenuButton:hover {{
            background-color: {_tc("BUTTON_HOVER")}; border-color: {_tc("BORDER_FOCUS")};
        }}
        QToolButton#presetMenuButton:focus {{
            border: 2px solid {_tc("BORDER_FOCUS")};
        }}
        QToolButton#presetMenuButton:disabled {{
            background-color: {_tc("PANEL_BG")}; color: {_tc("TEXT_DISABLED")};
            border-color: {_tc("BORDER_COLOR")};
        }}
        QToolButton#presetMenuButton::menu-indicator {{ image: none; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right; width: 24px;
            border-left: 1px solid {_tc("BORDER_COLOR")};
            border-top-right-radius: {RADIUS_MD}px; border-bottom-right-radius: {RADIUS_MD}px;
            background-color: {_tc("BUTTON_BG")};
        }}
        QComboBox::drop-down:hover {{ background-color: {_tc("BUTTON_HOVER")}; }}
        QComboBox::down-arrow {{
            image: url(icons:{arrow_icon}); width: 12px; height: 8px; margin-right: 3px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")}; border-radius: {RADIUS_SM}px;
            selection-background-color: {_tc("SELECTION_BG")};
            selection-color: {_tc("SELECTION_TEXT")}; outline: none;
        }}
        QComboBox QAbstractItemView::item {{ color: {_tc("TEXT_PRIMARY")}; padding: 4px 8px; }}
        QComboBox QAbstractItemView::item:selected {{
            background-color: {_tc("SELECTION_BG")}; color: {_tc("SELECTION_TEXT")};
        }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {_tc("BUTTON_HOVER")}; color: {_tc("TEXT_PRIMARY")};
        }}
        """

    # ── 分组框 ──────────────────────────────────────────────────────────

    @classmethod
    def group_box_title_margin(cls) -> int:
        """返回能为当前界面字体保留标题净空的分组框上边距。"""

        title_height = QFontMetrics(cast(Any, cls).font_for_role(FontRole.UI)).height()
        # 项目内分组布局至少还会提供 12px 的内容起始距离。这里按标题实际高度
        # 动态补足剩余空间，使常规字号和最大字号下都保留至少 4px 的净空。
        return max(8, title_height - 8)

    @classmethod
    def GROUP_BOX_STYLE(cls) -> str:
        title_margin = cls.group_box_title_margin()
        return f"""
        QGroupBox {{
            background-color: {_tc("PANEL_BG")}; border: 1px solid {_tc("BORDER_COLOR")};
            border-radius: {RADIUS_LG}px; margin-top: {title_margin}px;
            padding: 2px 4px 1px 4px;
            font-weight: bold; color: {_tc("TEXT_PRIMARY")};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px;
            left: 10px; color: {_tc("GROUP_TITLE_COLOR")};
        }}
        """

    # ── 列表控件 ────────────────────────────────────────────────────────

    @classmethod
    def LIST_WIDGET_STYLE(cls) -> str:
        return (
            f"""
        QListWidget {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 2px;
            outline: none;
        }}
        """
            f"""QListWidget::item {{ padding: 3px 6px; border-radius: {RADIUS_SM}px; """
            f"""color: {_tc("TEXT_PRIMARY")}; }}
        QListWidget::item:selected {{
            background-color: {_tc("SELECTION_BG")}; color: {_tc("SELECTION_TEXT")};
        }}
        QListWidget::item:hover {{ background-color: {_tc("BUTTON_HOVER")}; }}
        QListWidget:focus {{ border: 2px solid {_tc("BORDER_FOCUS")}; }}
        """
        )

    # ── 工具栏 ──────────────────────────────────────────────────────────

    @classmethod
    def TOOLBAR_STYLE(cls) -> str:
        return f"""
        QFrame#toolbar {{
            background-color: {_tc("TOOLBAR_BG")}; border-radius: {RADIUS_MD}px;
            border: 1px solid {_tc("BORDER_COLOR")};
        }}
        QFrame#toolbar QPushButton,
        QFrame#toolbar QToolButton {{
            background-color: transparent; color: {_tc("TEXT_PRIMARY")};
            border: none; border-radius: {RADIUS_SM}px; padding: 2px 6px;
        }}
        QFrame#toolbar QPushButton:hover,
        QFrame#toolbar QToolButton:hover {{ background-color: {_tc("BUTTON_HOVER")}; }}
        QFrame#toolbar QPushButton:focus,
        QFrame#toolbar QToolButton:focus {{
            border: 1px solid {_tc("BORDER_FOCUS")};
        }}
        QFrame#toolbar QPushButton#exit_btn:hover,
        QFrame#toolbar QToolButton#exit_btn:hover {{
            background-color: {_tc("BUTTON_DANGER")}; color: #ffffff;
        }}
        QFrame#toolbar QLabel {{
            color: {_tc("TEXT_PRIMARY")};
        }}
        QFrame#toolbar QLabel#toolbarTitle {{ font-weight: bold; }}
        """

    @classmethod
    def MENU_STYLE(cls) -> str:
        """返回深浅主题一致的上下文菜单样式。"""

        return f"""
        QMenu {{
            background-color: {_tc("PANEL_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")}; border-radius: {RADIUS_SM}px;
            padding: 4px;
        }}
        QMenu::item {{
            color: {_tc("TEXT_PRIMARY")}; padding: 6px 24px 6px 10px;
            border-radius: {RADIUS_SM}px;
        }}
        QMenu::item:selected {{
            background-color: {_tc("BUTTON_HOVER")}; color: {_tc("TEXT_PRIMARY")};
        }}
        QMenu::item:disabled {{ color: {_tc("TEXT_DISABLED")}; }}
        QMenu::separator {{
            height: 1px; background-color: {_tc("BORDER_COLOR")}; margin: 4px 8px;
        }}
        """

    # ── 状态栏 ──────────────────────────────────────────────────────────

    @classmethod
    def STATUS_BAR_STYLE(cls) -> str:
        return (
            f"QStatusBar {{ background-color: {_tc('PANEL_BG')}; "
            f"color: {_tc('TEXT_PRIMARY')}; border-top: 1px solid {_tc('BORDER_COLOR')}; }}"
        )

    # ── 带勾选标记的设备列表 ────────────────────────────────────────────

    @classmethod
    def DEVICE_LIST_STYLE(cls) -> str:
        return f"""
        QListWidget#deviceList {{
            background-color: {_tc("INPUT_BG")}; color: {_tc("TEXT_PRIMARY")};
            border: 1px solid {_tc("BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 2px; outline: none;
        }}
        QListWidget#deviceList::item {{ padding: 3px 6px; color: {_tc("TEXT_PRIMARY")}; }}
        QListWidget#deviceList::item:selected {{
            background-color: {_tc("SELECTION_BG")}; color: {_tc("SELECTION_TEXT")};
        }}
        QListWidget#deviceList::item:hover {{ background-color: {_tc("BUTTON_HOVER")}; }}
        QListWidget#deviceList:focus {{ border: 2px solid {_tc("BORDER_FOCUS")}; }}
        QListWidget::indicator {{ width: 14px; height: 14px; }}
        QListWidget::indicator:unchecked {{
            image: none; border: 2px solid {_tc("BORDER_COLOR")};
            border-radius: 3px; background-color: {_tc("INPUT_BG")};
        }}
        QListWidget::indicator:checked {{ image: url(icons:check.svg); border: none; }}
        """

    # ── PANEL_BASE_STYLE 组合样式 ───────────────────────────────────────

    @classmethod
    def PANEL_BASE_STYLE(cls) -> str:
        return (
            cls.BUTTON_QSS()
            + cls.INPUT_STYLE()
            + cls.LIST_WIDGET_STYLE()
            + f"QWidget {{ background-color: {_tc('WINDOW_BG')}; color: {_tc('TEXT_PRIMARY')}; }}"
            + "QFrame { background-color: transparent; border: none; "
            + f"color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QLabel {{ color: {_tc('TEXT_PRIMARY')}; background-color: transparent; }}"
            + f"QCheckBox {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QCheckBox:focus {{ border: 1px solid {_tc('BORDER_FOCUS')}; "
            + f"border-radius: {RADIUS_SM}px; }}"
            + cls.STATUS_BAR_STYLE()
            + f"QTableWidget {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + f"QTableWidget:focus {{ border: 2px solid {_tc('BORDER_FOCUS')}; }}"
            + "QPlainTextEdit:focus, QTextEdit:focus "
            + f"{{ border: 2px solid {_tc('BORDER_FOCUS')}; }}"
            + f"QTabBar:focus {{ border: 2px solid {_tc('BORDER_FOCUS')}; "
            + f"border-radius: {RADIUS_SM}px; }}"
            + f"QHeaderView::section {{ color: {_tc('TEXT_PRIMARY')}; }}"
            + cls.SCROLLBAR_STYLE()
        )
