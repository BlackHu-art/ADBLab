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


def _arrow_icons(theme: str) -> tuple[str, str]:
    """返回按主题固化的下拉/上拉箭头 SVG 资源名。

    QSS 通过 ``url(icons:...)`` 加载 SVG 时不会继承控件前景色，因此项目预先为每个主题
    导出描边色固化的资源（``caret-down-qss-{light,dark}.svg`` 等）。
    """

    theme_suffix = "dark" if theme == "Dark" else "light"
    return (
        f"caret-down-qss-{theme_suffix}.svg",
        f"caret-up-qss-{theme_suffix}.svg",
    )

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

    # ── 输入控件 ────────────────────────────────────────────────────────

    @classmethod
    def COMBO_BOX_STYLE(cls) -> str:
        """FluentComboBox（原生 QComboBox 自研封装）的下拉框主题样式。

        设备地址下拉框依赖原生 QComboBox 的 ``setModel``/``setView`` 表格视图
        （品牌/型号/IP 三列），qfluentwidgets ComboBox/EditableComboBox 无该能力，
        故保留此样式。
        """
        theme = cast(Any, cls).current_theme()
        cached = _cached_style("COMBO_BOX_STYLE", theme)
        if cached is not None:
            return cached
        arrow_icon, _ = _arrow_icons(theme)
        return _store_style(
            "COMBO_BOX_STYLE",
            theme,
            f"""
        QComboBox {{
            background-color: {_color(theme, "INPUT_BG")}; color: {_color(theme, "TEXT_PRIMARY")};
            border: 1px solid {_color(theme, "BORDER_COLOR")}; border-radius: {RADIUS_MD}px;
            padding: 3px 6px; selection-background-color: {_color(theme, "SELECTION_BG")};
        }}
        QComboBox:focus {{
            border-color: {_color(theme, "BORDER_FOCUS")};
        }}
        QComboBox:disabled {{
            background-color: {_color(theme, "PANEL_BG")}; color: {_color(theme, "TEXT_DISABLED")};
        }}
        QComboBox QLineEdit {{
            background-color: transparent; border: none; border-radius: 0;
            padding: 0 4px; color: {_color(theme, "TEXT_PRIMARY")};
        }}
        QComboBox QLineEdit:disabled {{
            background-color: transparent; color: {_color(theme, "TEXT_DISABLED")};
        }}
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
