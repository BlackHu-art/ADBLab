"""提供 ADBLab 控件使用的 QSS 样式模板（tokens→QSS 生成器）。

颜色一律经 :mod:`gui.styles.tokens`（与 ``THEMES`` 单一来源）读取；纯字符串模板
按 ``(样式名, 当前主题)`` 记忆化——主题取自 ``BaseStyles.current_theme()``（测试
会 patch 该 classmethod，不得读主题模块全局），主题切换后自动重建；字体度量与
按主题选图标的运行时注入不参与缓存（UI 重做 P0）。
"""

from typing import Any, cast

from PySide6.QtGui import QFontMetrics

from . import tokens as _tokens
from .typography import FontRole

# 兼容旧引用：圆角常量与 _tc 取色入口保持同名可用（golden 契约）。
RADIUS_SM = _tokens.RADIUS["sm"]
RADIUS_MD = _tokens.RADIUS["md"]
RADIUS_LG = _tokens.RADIUS["lg"]
RADIUS_XL = _tokens.RADIUS["xl"]

# 取色与缓存键同源：颜色解析按同一 theme 参数进行（审查修复：避免 patch
# current_theme 时跨主题缓存污染）。
def _color(theme: str, key: str) -> str:
    return _tokens.color_token_for(theme, key)

_STYLE_CACHE: dict[str, str] = {}


def _cached_style(name: str, theme: str) -> str | None:
    """按 (样式名, 主题) 读取记忆化结果；无缓存返回 None。"""

    return _STYLE_CACHE.get(f"{name}:{theme}")


def _store_style(name: str, theme: str, value: str) -> str:
    """把生成结果写入记忆化缓存并返回原值。"""

    _STYLE_CACHE[f"{name}:{theme}"] = value
    return value


class QSSMixin:
    """通过 BaseStyles 提供全部 QSS 模板方法。"""

    # ── 滚动条 ──────────────────────────────────────────────────────────

    @classmethod
    def SCROLLBAR_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("SCROLLBAR_STYLE", theme)
        if cached is not None:
            return cached
        h = _color(theme, "SCROLLBAR_HANDLE")
        hh = _color(theme, "SCROLLBAR_HANDLE_HOVER")
        return _store_style(
            "SCROLLBAR_STYLE",
            theme,
            f"""
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
        QScrollBar::handle:horizontal:pressed {{ background: {_color(theme, "BORDER_FOCUS")}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0; width: 0; border: none; background: none;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QScrollBar::corner {{ background: transparent; }}
        """,
        )

    # ── 按钮 ────────────────────────────────────────────────────────────

    @classmethod
    def BUTTON_BASE(cls) -> str:
        return f"""
            border-radius: {RADIUS_MD}px; padding: 3px 8px;
        """

    @classmethod
    def BUTTON_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("BUTTON_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "BUTTON_STYLE",
            theme,
            f"""
        QPushButton {{
            {cls.BUTTON_BASE()}
            background-color: {_color(theme, "BUTTON_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")};
        }}
        QPushButton:hover {{
            background-color: {_color(theme, "BUTTON_HOVER")};
            border-color: {_color(theme, "BORDER_FOCUS")};
        }}
        QPushButton:pressed {{ background-color: {_color(theme, "BUTTON_PRESSED")}; }}
        QPushButton:focus {{ border: 2px solid {_color(theme, "BORDER_FOCUS")}; }}
        QPushButton:disabled {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_DISABLED")};
            border-color: {_color(theme, "BORDER_COLOR")};
        }}
        """,
        )

    @classmethod
    def ACCENT_BUTTON_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("ACCENT_BUTTON_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "ACCENT_BUTTON_STYLE",
            theme,
            f"""
        QPushButton#accent {{
            {cls.BUTTON_BASE()}
            background-color: {_color(theme, "BUTTON_ACCENT")}; color: #ffffff;
            border: 1px solid {_color(theme, "BUTTON_ACCENT")};
        }}
        QPushButton#accent:hover {{ background-color: {_color(theme, "BUTTON_ACCENT_HOVER")}; }}
        QPushButton#accent:pressed {{ background-color: {_color(theme, "BUTTON_ACCENT_PRESSED")}; }}
        QPushButton#accent:focus {{ border: 2px solid {_color(theme, "TEXT_PRIMARY")}; }}
        QPushButton#accent:disabled {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_DISABLED")};
            border-color: {_color(theme, "BORDER_COLOR")};
        }}
        """,
        )

    @classmethod
    def DANGER_BUTTON_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("DANGER_BUTTON_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "DANGER_BUTTON_STYLE",
            theme,
            f"""
        QPushButton#danger {{
            {cls.BUTTON_BASE()}
            background-color: {_color(theme, "BUTTON_DANGER")}; color: #ffffff;
            border: 1px solid {_color(theme, "BUTTON_DANGER")};
        }}
        QPushButton#danger:hover {{ background-color: {_color(theme, "BUTTON_DANGER_HOVER")}; }}
        QPushButton#danger:pressed {{ background-color: {_color(theme, "BUTTON_DANGER")}; }}
        QPushButton#danger:focus {{ border: 2px solid {_color(theme, "TEXT_PRIMARY")}; }}
        QPushButton#danger:disabled {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_DISABLED")};
            border-color: {_color(theme, "BORDER_COLOR")};
        }}
        """,
        )

    @classmethod
    def BUTTON_QSS(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("BUTTON_QSS", theme)
        if cached is not None:
            return cached
        return _store_style(
            "BUTTON_QSS",
            theme,
            cls.BUTTON_STYLE() + cls.ACCENT_BUTTON_STYLE() + cls.DANGER_BUTTON_STYLE(),
        )

    # ── 输入控件 ────────────────────────────────────────────────────────

    @classmethod
    def INPUT_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("INPUT_STYLE", theme)
        if cached is not None:
            return cached
        # QSS 加载 SVG 时不会继承控件的前景色，因此使用按主题固化描边色的资源。
        theme_suffix = "dark" if theme == "Dark" else "light"
        arrow_icon = f"caret-down-qss-{theme_suffix}.svg"
        up_arrow_icon = f"caret-up-qss-{theme_suffix}.svg"
        return _store_style(
            "INPUT_STYLE",
            theme,
            f"""
        QLineEdit, QComboBox, QSpinBox {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 3px 6px; selection-background-color: {_color(theme, "SELECTION_BG")};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
            border-color: {_color(theme, "BORDER_FOCUS")};
        }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
            background-color: {_color(theme, "PANEL_BG")}; color: {_color(theme, "TEXT_DISABLED")};
        }}
        QSpinBox[inputInvalid="true"], QSpinBox[inputInvalid="true"]:focus {{
            border: 2px solid {_color(theme, "BUTTON_DANGER")};
        }}
        QSpinBox QLineEdit {{
            background-color: transparent; border: none; border-radius: 0;
            padding: 0 4px; color: {_color(theme, "TEXT_PRIMARY")};
        }}
        QSpinBox QLineEdit:disabled {{
            background-color: transparent; color: {_color(theme, "TEXT_DISABLED")};
        }}
        QComboBox QLineEdit {{
            background-color: transparent; border: none; border-radius: 0;
            padding: 0 4px; color: {_color(theme, "TEXT_PRIMARY")};
        }}
        QComboBox QLineEdit:disabled {{
            background-color: transparent; color: {_color(theme, "TEXT_DISABLED")};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            subcontrol-origin: border; width: 18px;
            background-color: {_color(theme, "BUTTON_BG")};
            border-left: 1px solid {_color(theme, "BORDER_COLOR")};
        }}
        QSpinBox::up-button {{
            subcontrol-position: top right; border-top-right-radius: {RADIUS_MD}px;
        }}
        QSpinBox::down-button {{
            subcontrol-position: bottom right; border-bottom-right-radius: {RADIUS_MD}px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: {_color(theme, "BUTTON_HOVER")};
        }}
        QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {{
            background-color: {_color(theme, "PANEL_BG")};
            border-left-color: {_color(theme, "BORDER_COLOR")};
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
            background-color: {_color(theme, "BUTTON_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 3px 6px; qproperty-icon: url(icons:{arrow_icon});
        }}
        QToolButton#presetMenuButton:hover {{
            background-color: {_color(theme, "BUTTON_HOVER")};
            border-color: {_color(theme, "BORDER_FOCUS")};
        }}
        QToolButton#presetMenuButton:focus {{
            border: 2px solid {_color(theme, "BORDER_FOCUS")};
        }}
        QToolButton#presetMenuButton:disabled {{
            background-color: {_color(theme, "PANEL_BG")}; color: {_color(theme, "TEXT_DISABLED")};
            border-color: {_color(theme, "BORDER_COLOR")};
        }}
        QToolButton#presetMenuButton::menu-indicator {{ image: none; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right; width: 24px;
            border-left: 1px solid {_color(theme, "BORDER_COLOR")};
            border-top-right-radius: {RADIUS_MD}px; border-bottom-right-radius: {RADIUS_MD}px;
            background-color: {_color(theme, "BUTTON_BG")};
        }}
        QComboBox::drop-down:hover {{ background-color: {_color(theme, "BUTTON_HOVER")}; }}
        QComboBox::down-arrow {{
            image: url(icons:{arrow_icon}); width: 12px; height: 8px; margin-right: 3px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_SM}px;
            selection-background-color: {_color(theme, "SELECTION_BG")};
            selection-color: {_color(theme, "SELECTION_TEXT")}; outline: none;
        }}
        QComboBox QAbstractItemView::item {{
            color: {_color(theme, "TEXT_PRIMARY")}; padding: 4px 8px;
        }}
        QComboBox QAbstractItemView::item:selected {{
            background-color: {_color(theme, "SELECTION_BG")};
            color: {_color(theme, "SELECTION_TEXT")};
        }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {_color(theme, "BUTTON_HOVER")};
            color: {_color(theme, "TEXT_PRIMARY")};
        }}
        """,
        )

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
        # 字体刻度参与缓存键：group_box_title_margin 依赖当前 UI 字号，
        # 字号变化而主题不变时也必须重建（typography 契约）。
        title_margin = cls.group_box_title_margin()
        theme = cast(Any, cls).current_theme()
        cache_name = f"GROUP_BOX_STYLE:{title_margin}"
        cached = _STYLE_CACHE.get(f"{cache_name}:{theme}")
        if cached is not None:
            return cached
        return _store_style(
            cache_name,
            theme,
            f"""
        QGroupBox {{
            background-color: {_color(theme, "PANEL_BG")};
            border: 1px solid {_color(theme, "BORDER_COLOR")};
            border-radius: {RADIUS_LG}px; margin-top: {title_margin}px;
            padding: 2px 4px 1px 4px;
            font-weight: bold; color: {_color(theme, "TEXT_PRIMARY")};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px;
            left: 10px; color: {_color(theme, "GROUP_TITLE_COLOR")};
        }}
        """,
        )

    # ── 列表控件 ────────────────────────────────────────────────────────

    @classmethod
    def LIST_WIDGET_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("LIST_WIDGET_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "LIST_WIDGET_STYLE",
            theme,
            (
                f"""
        QListWidget {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 2px;
            outline: none;
        }}
        """
                f"""QListWidget::item {{ padding: 3px 6px; border-radius: {RADIUS_SM}px; """
                f"""color: {_color(theme, "TEXT_PRIMARY")}; }}
        QListWidget::item:selected {{
            background-color: {_color(theme, "SELECTION_BG")};
            color: {_color(theme, "SELECTION_TEXT")};
        }}
        QListWidget::item:hover {{ background-color: {_color(theme, "BUTTON_HOVER")}; }}
        QListWidget:focus {{ border: 2px solid {_color(theme, "BORDER_FOCUS")}; }}
        """
            ),
        )

    # ── 工具栏 ──────────────────────────────────────────────────────────

    @classmethod
    def TOOLBAR_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("TOOLBAR_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "TOOLBAR_STYLE",
            theme,
            f"""
        QFrame#toolbar {{
            background-color: {_color(theme, "TOOLBAR_BG")}; border-radius: {RADIUS_MD}px;
            border: 1px solid {_color(theme, "BORDER_COLOR")};
        }}
        QFrame#toolbar QPushButton,
        QFrame#toolbar QToolButton {{
            background-color: transparent; color: {_color(theme, "TEXT_PRIMARY")};
            border: none; border-radius: {RADIUS_SM}px; padding: 2px 6px;
        }}
        QFrame#toolbar QPushButton:hover,
        QFrame#toolbar QToolButton:hover {{ background-color: {_color(theme, "BUTTON_HOVER")}; }}
        QFrame#toolbar QPushButton:focus,
        QFrame#toolbar QToolButton:focus {{
            border: 1px solid {_color(theme, "BORDER_FOCUS")};
        }}
        QFrame#toolbar QPushButton#exit_btn:hover,
        QFrame#toolbar QToolButton#exit_btn:hover {{
            background-color: {_color(theme, "BUTTON_DANGER")}; color: #ffffff;
        }}
        QFrame#toolbar QLabel {{
            color: {_color(theme, "TEXT_PRIMARY")};
        }}
        QFrame#toolbar QLabel#toolbarTitle {{ font-weight: bold; }}
        """,
        )

    @classmethod
    def MENU_STYLE(cls) -> str:
        """返回深浅主题一致的上下文菜单样式。"""

        theme = cast(Any, cls).current_theme()
        cached = _cached_style("MENU_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "MENU_STYLE",
            theme,
            f"""
        QMenu {{
            background-color: {_color(theme, "PANEL_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_SM}px;
            padding: 4px;
        }}
        QMenu::item {{
            color: {_color(theme, "TEXT_PRIMARY")}; padding: 6px 24px 6px 10px;
            border-radius: {RADIUS_SM}px;
        }}
        QMenu::item:selected {{
            background-color: {_color(theme, "BUTTON_HOVER")};
            color: {_color(theme, "TEXT_PRIMARY")};
        }}
        QMenu::item:disabled {{ color: {_color(theme, "TEXT_DISABLED")}; }}
        QMenu::separator {{
            height: 1px; background-color: {_color(theme, "BORDER_COLOR")}; margin: 4px 8px;
        }}
        """,
        )

    # ── 状态栏 ──────────────────────────────────────────────────────────

    @classmethod
    def STATUS_BAR_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("STATUS_BAR_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "STATUS_BAR_STYLE",
            theme,
            (
                f"QStatusBar {{ background-color: {_color(theme, 'PANEL_BG')}; "
                f"color: {_color(theme, 'TEXT_PRIMARY')}; "
                f"border-top: 1px solid {_color(theme, 'BORDER_COLOR')}; }}"
            ),
        )

    # ── 带勾选标记的设备列表 ────────────────────────────────────────────

    @classmethod
    def DEVICE_LIST_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("DEVICE_LIST_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "DEVICE_LIST_STYLE",
            theme,
            f"""
        QListWidget#deviceList {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 2px; outline: none;
        }}
        QListWidget#deviceList::item {{ padding: 3px 6px; color: {_color(theme, "TEXT_PRIMARY")}; }}
        QListWidget#deviceList::item:selected {{
            background-color: {_color(theme, "SELECTION_BG")};
            color: {_color(theme, "SELECTION_TEXT")};
        }}
        QListWidget#deviceList::item:hover {{ background-color: {_color(theme, "BUTTON_HOVER")}; }}
        QListWidget#deviceList:focus {{ border: 2px solid {_color(theme, "BORDER_FOCUS")}; }}
        QListWidget::indicator {{ width: 14px; height: 14px; }}
        QListWidget::indicator:unchecked {{
            image: none; border: 2px solid {_color(theme, "BORDER_COLOR")};
            border-radius: 3px; background-color: {_color(theme, "INPUT_BG")};
        }}
        QListWidget::indicator:checked {{ image: url(icons:check.svg); border: none; }}
        """,
        )

    # ── PANEL_BASE_STYLE 组合样式 ───────────────────────────────────────

    @classmethod
    def PANEL_BASE_STYLE(cls) -> str:
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("PANEL_BASE_STYLE", theme)
        if cached is not None:
            return cached
        return _store_style(
            "PANEL_BASE_STYLE",
            theme,
            (
                cls.BUTTON_QSS()
                + cls.INPUT_STYLE()
                + cls.LIST_WIDGET_STYLE()
                + f"QWidget {{ background: transparent; color: {_color(theme, 'TEXT_PRIMARY')}; }}"
                + "QDialog { background-color: "
                + f"{_color(theme, 'WINDOW_BG')}; color: {_color(theme, 'TEXT_PRIMARY')}; }}"
                + "QFrame { background-color: transparent; border: none; "
                + f"color: {_color(theme, 'TEXT_PRIMARY')}; }}"
                + f"QLabel {{ color: {_color(theme, 'TEXT_PRIMARY')}; "
                + "background-color: transparent; }"
                + f"QCheckBox, QRadioButton {{ color: {_color(theme, 'TEXT_PRIMARY')}; "
                + "background-color: transparent; }"
                + f"QCheckBox:focus {{ border: 1px solid {_color(theme, 'BORDER_FOCUS')}; "
                + f"border-radius: {RADIUS_SM}px; }}"
                + cls.STATUS_BAR_STYLE()
                + f"QTableWidget {{ color: {_color(theme, 'TEXT_PRIMARY')}; }}"
                + f"QTableWidget:focus {{ border: 2px solid {_color(theme, 'BORDER_FOCUS')}; }}"
                + "QPlainTextEdit:focus, QTextEdit:focus "
                + f"{{ border: 2px solid {_color(theme, 'BORDER_FOCUS')}; }}"
                + f"QTabBar:focus {{ border: 2px solid {_color(theme, 'BORDER_FOCUS')}; "
                + f"border-radius: {RADIUS_SM}px; }}"
                + f"QHeaderView::section {{ color: {_color(theme, 'TEXT_PRIMARY')}; }}"
                + cls.SCROLLBAR_STYLE()
            ),
        )
