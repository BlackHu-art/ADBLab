"""ADBLab design tokens：原始色板、语义色与组件态/间距/圆角/焦点环三层体系。

分层约定：
- L1 ``RAW_PALETTE``：与主题无关的原始色值（图表系列色带、语义严重度色等）。
- L2 语义色：以 :data:`gui.styles.theme.THEMES` 既有键集为唯一命名空间，
  通过 :func:`semantic_view` / :func:`color_token` 读取，与旧 ``BaseStyles.color``
  完全同源，杜绝双色板漂移。
- L3 组件态/间距/圆角/焦点环：``SPACING`` / ``RADIUS`` / ``FOCUS_RING`` 及派生函数。

阴影在 Qt Widgets QSS 中不可表达，本体系一律用边框/描边 token 扁平化表达，
不产生逐控件 QGraphicsDropShadowEffect。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gui.styles.theme import THEMES  # noqa: F401  仅供类型标注引用

# ── L1 原始色板（与主题无关的基色，供图表/严重度等跨主题语义使用）─────────

RAW_PALETTE = {
    # 图表系列色带（QtCharts/P0 起供 MobilePerf 图表与任务中心徽标使用）
    "CHART_SERIES": [
        "#0078d4",
        "#e07a5f",
        "#81b29a",
        "#f2cc8f",
        "#9b5de5",
        "#00b4d8",
        "#ee6c4d",
        "#3d405b",
    ],
    # 严重度语义原始色（语义色层在此之上按主题映射）
    "SEVERITY": {
        "info": "#0078d4",
        "success": "#167d2d",
        "warning": "#e3a008",
        "error": "#d32f2f",
        "critical": "#c51162",
    },
    # 白色文本（强调按钮前景，不随主题变化）
    "TEXT_ON_ACCENT": "#ffffff",
}

# ── L3 间距 / 圆角 / 焦点环 ───────────────────────────────────────────────

SPACING = {
    "xs": 2,
    "sm": 4,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "xxl": 24,
}

# 圆角与旧 RADIUS_SM/MD/LG/XL 常量保持数值一致（golden 契约）。
RADIUS = {
    "sm": 4,
    "md": 6,
    "lg": 8,
    "xl": 12,
}

FOCUS_RING = {
    # 焦点环统一为 2px 描边 + 主题 BORDER_FOCUS 色；粗细与旧契约一致。
    "width": 2,
    "color_key": "BORDER_FOCUS",
}


# ── L2 语义色读取（THEMES 单一来源）───────────────────────────────────────


def semantic_view() -> dict[str, str]:
    """返回当前主题的语义色视图（浅拷贝，键集与 THEMES 一致）。"""

    from gui.styles.theme import _current_theme

    theme_name = _current_theme
    from gui.styles.theme import THEMES

    return dict(THEMES.get(theme_name, THEMES["Light"]))


def color_token(key: str) -> str:
    """按 token 键读取当前主题颜色；与 ``theme._tc`` 完全同源。"""

    from gui.styles.theme import _tc

    return _tc(key)


def color_token_for(theme: str, key: str) -> str:
    """按指定主题读取 token 颜色（供 QSS 生成器把颜色与缓存键绑定同一主题源）。"""

    from gui.styles.theme import THEMES

    palette = THEMES.get(theme, THEMES["Light"])
    return palette.get(key, THEMES["Light"].get(key, "#000000"))


def theme_name() -> str:
    """返回当前主题名（供 QSS 生成器缓存键使用）。"""

    from gui.styles.theme import _current_theme

    return _current_theme


def spacing(step: str) -> int:
    """返回间距 token；未知步长回退 ``md``。"""

    return SPACING.get(step, SPACING["md"])


def radius(step: str) -> int:
    """返回圆角 token；未知步长回退 ``md``。"""

    return RADIUS.get(step, RADIUS["md"])


__all__ = [
    "FOCUS_RING",
    "RADIUS",
    "RAW_PALETTE",
    "SPACING",
    "color_token",
    "color_token_for",
    "radius",
    "semantic_view",
    "spacing",
    "theme_name",
]
