"""提供应用级字体配置、字体角色和变更通知。"""

from __future__ import annotations

import platform
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication

UI_FONT_SIZE_MIN = 8
UI_FONT_SIZE_MAX = 22
LOG_FONT_SIZE_MIN = 7
LOG_FONT_SIZE_MAX = 16

_PLATFORM_UI_FONT = {
    "Windows": "Segoe UI",
    "Darwin": "SF Pro Display",
}.get(platform.system(), "Noto Sans")

_PLATFORM_MONO_FONT = {
    "Windows": "Consolas",
    "Darwin": "SF Mono",
}.get(platform.system(), "DejaVu Sans Mono")


class FontRole(str, Enum):
    """定义应用内稳定的字体用途，避免各窗口自行拼装字号和字体族。"""

    UI = "ui"
    UI_SMALL = "ui_small"
    MONO = "mono"
    LOG = "log"
    TITLE = "title"


@dataclass(frozen=True, slots=True)
class FontConfig:
    """保存已经校验并解析为可用字体族的字体配置。"""

    ui_family: str
    ui_size: int
    log_size: int
    mono_family: str


def _safe_size(value: object, default: int, minimum: int, maximum: int) -> int:
    """将外部字号转换到安全范围，无法解析时回退到默认值。"""

    if isinstance(value, bool):
        return default
    try:
        size = int(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, size))


def _system_font_family(system_font: QFontDatabase.SystemFont, fallback: str) -> str:
    """读取 Qt 系统字体；无图形应用或字体信息缺失时使用平台回退值。"""

    if QGuiApplication.instance() is None:
        return fallback
    try:
        family = QFontDatabase.systemFont(system_font).family().strip()
    except (RuntimeError, TypeError):
        return fallback
    return family or fallback


def system_ui_font_family() -> str:
    """返回当前系统建议的界面字体族。"""

    return _system_font_family(QFontDatabase.SystemFont.GeneralFont, _PLATFORM_UI_FONT)


def system_mono_font_family() -> str:
    """返回当前系统建议的等宽字体族。"""

    return _system_font_family(QFontDatabase.SystemFont.FixedFont, _PLATFORM_MONO_FONT)


def _available_families() -> dict[str, str]:
    """返回以不区分大小写名称索引的已安装字体。"""

    if QGuiApplication.instance() is None:
        return {}
    try:
        families = QFontDatabase.families()
    except (RuntimeError, TypeError):
        return {}
    return {
        family.strip().casefold(): family.strip()
        for family in families
        if isinstance(family, str) and family.strip()
    }


def resolve_ui_font_family(value: object) -> str:
    """解析用户字体设置，不可用或系统默认设置均回退到 Qt 系统字体。"""

    requested = str(value or "").strip()
    fallback = system_ui_font_family()
    if not requested or requested.casefold() == "system default":
        return fallback

    available = _available_families()
    if not available:
        return fallback
    return available.get(requested.casefold(), fallback)


def font_config_from_mapping(values: Mapping[str, object]) -> FontConfig:
    """从设置映射创建不可变且经过边界校验的字体配置。"""

    return FontConfig(
        ui_family=resolve_ui_font_family(values.get("font_family", "")),
        ui_size=_safe_size(
            values.get("ui_font_size", 12),
            default=12,
            minimum=UI_FONT_SIZE_MIN,
            maximum=UI_FONT_SIZE_MAX,
        ),
        log_size=_safe_size(
            values.get("log_font_size", 9),
            default=9,
            minimum=LOG_FONT_SIZE_MIN,
            maximum=LOG_FONT_SIZE_MAX,
        ),
        mono_family=system_mono_font_family(),
    )


def font_for_config(
    config: FontConfig,
    role: FontRole | str,
    size: int | None = None,
) -> QFont:
    """根据不可变配置和字体角色创建 QFont。"""

    role = FontRole(role)
    if role is FontRole.LOG:
        family = config.mono_family
        default_size = config.log_size
        style_hint = QFont.StyleHint.Monospace
    elif role is FontRole.MONO:
        family = config.mono_family
        default_size = config.ui_size
        style_hint = QFont.StyleHint.Monospace
    elif role is FontRole.UI_SMALL:
        family = config.ui_family
        default_size = max(UI_FONT_SIZE_MIN, config.ui_size - 1)
        style_hint = QFont.StyleHint.SansSerif
    elif role is FontRole.TITLE:
        family = config.ui_family
        default_size = min(UI_FONT_SIZE_MAX + 4, config.ui_size + 4)
        style_hint = QFont.StyleHint.SansSerif
    else:
        family = config.ui_family
        default_size = config.ui_size
        style_hint = QFont.StyleHint.SansSerif

    requested_size = (
        default_size
        if size is None
        else _safe_size(
            size,
            default=default_size,
            minimum=LOG_FONT_SIZE_MIN,
            maximum=UI_FONT_SIZE_MAX + 4,
        )
    )
    font = QFont(family, requested_size)
    font.setStyleHint(style_hint)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    if role is FontRole.TITLE:
        font.setBold(True)
    return font


class TypographyManager(QObject):
    """维护应用唯一字体配置，并按实际变化发送细粒度信号。"""

    ui_font_changed = Signal(object)
    log_font_changed = Signal(object)
    fonts_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._config = font_config_from_mapping({})

    @property
    def config(self) -> FontConfig:
        """返回当前不可变字体配置。"""

        return self._config

    def apply(self, config: FontConfig) -> bool:
        """应用配置到 QApplication，并仅为发生变化的字体角色发送信号。"""

        previous = self._config
        ui_changed = previous.ui_family != config.ui_family or previous.ui_size != config.ui_size
        log_changed = (
            previous.mono_family != config.mono_family or previous.log_size != config.log_size
        )
        changed = ui_changed or log_changed
        self._config = config
        self.apply_application_font()

        if ui_changed:
            self.ui_font_changed.emit(config)
        if log_changed:
            self.log_font_changed.emit(config)
        if changed:
            self.fonts_changed.emit(config)
        return changed

    def apply_application_font(self) -> None:
        """把界面字体设为 QApplication 默认字体，使未单独设置的控件自动继承。"""

        app = QGuiApplication.instance()
        if app is not None:
            cast(QGuiApplication, app).setFont(self.font_for_role(FontRole.UI))

    def font_for_role(self, role: FontRole | str, size: int | None = None) -> QFont:
        """按角色创建字体，调用方可为少量特殊场景覆盖字号。"""

        return font_for_config(self._config, role, size)

    def control_height(
        self,
        minimum: int = 28,
        role: FontRole | str = FontRole.UI,
        padding: int = 10,
    ) -> int:
        """根据字体度量返回不会裁切文字的最小控件高度。"""

        return max(minimum, QFontMetrics(self.font_for_role(role)).height() + padding)


typography_manager = TypographyManager()


__all__ = [
    "FontConfig",
    "FontRole",
    "LOG_FONT_SIZE_MAX",
    "LOG_FONT_SIZE_MIN",
    "TypographyManager",
    "UI_FONT_SIZE_MAX",
    "UI_FONT_SIZE_MIN",
    "font_config_from_mapping",
    "font_for_config",
    "resolve_ui_font_family",
    "system_mono_font_family",
    "system_ui_font_family",
    "typography_manager",
]
