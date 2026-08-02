"""提供字体核心层的 BaseStyles 兼容入口。"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontMetrics

from .typography import (
    FontConfig,
    FontRole,
    font_config_from_mapping,
    font_for_config,
    system_mono_font_family,
    system_ui_font_family,
    typography_manager,
)

# 旧 QSS 模板仍按映射读取字体；该映射仅作为兼容投影，由字体核心统一更新。
_font = {
    "FAMILY": system_ui_font_family(),
    "UI": 12,
    "LOG": 9,
}

DEFAULT_FONT_FAMILY = _font["FAMILY"]
LOG_FONT = system_mono_font_family()
LOG_FONT_SIZE = 9


class FontMixin:
    """通过 BaseStyles 暴露字体角色、变更信号和旧版字体工厂。"""

    DEFAULT_FONT_FAMILY: str = DEFAULT_FONT_FAMILY
    LOG_FONT: str = LOG_FONT
    LOG_FONT_SIZE: int = LOG_FONT_SIZE
    DEFAULT_FONT_SIZE: int = _font["UI"]
    LOG_FONT_SIZE_VAR: int = _font["LOG"]

    ui_font_changed = typography_manager.ui_font_changed
    log_font_changed = typography_manager.log_font_changed
    fonts_changed = typography_manager.fonts_changed

    @classmethod
    def reload_from_settings(cls) -> FontConfig:
        """读取、校验并应用持久化字体设置，不触发主题变更信号。"""

        from core.settings_manager import AppSettings

        settings = AppSettings.instance()
        config = font_config_from_mapping(
            {
                "font_family": settings.get("font_family", ""),
                "ui_font_size": settings.get("ui_font_size", 12),
                "log_font_size": settings.get("log_font_size", 9),
            }
        )
        # 信号使用直接连接时会同步执行槽函数，因此先更新旧属性和 QSS 投影，
        # 再由管理器发送通知，确保观察者只会读取到完整的新配置。
        cls._sync_legacy_values(config)
        typography_manager.apply(config)
        return config

    @classmethod
    def _sync_legacy_values(cls, config: FontConfig) -> None:
        """同步旧属性与 QSS 映射，保证存量模块继续使用同一份配置。"""

        _font.update(
            {
                "FAMILY": config.ui_family,
                "UI": config.ui_size,
                "LOG": config.log_size,
            }
        )
        for target in (FontMixin, cls):
            target.DEFAULT_FONT_FAMILY = config.ui_family
            target.DEFAULT_FONT_SIZE = config.ui_size
            target.LOG_FONT = config.mono_family
            target.LOG_FONT_SIZE_VAR = config.log_size

    @classmethod
    def current_font_config(cls) -> FontConfig:
        """返回当前不可变字体配置。"""

        return typography_manager.config

    @classmethod
    def font_for_role(cls, role: FontRole | str, size: int | None = None) -> QFont:
        """按统一字体角色创建 QFont。"""

        # 正常运行时这些兼容属性始终是 FontConfig 的同步投影；使用投影构造字体
        # 还可兼容少量旧代码和测试直接覆写类属性的行为。
        config = FontConfig(
            ui_family=cls.DEFAULT_FONT_FAMILY,
            ui_size=int(cls.DEFAULT_FONT_SIZE),
            log_size=int(cls.LOG_FONT_SIZE_VAR),
            mono_family=cls.LOG_FONT,
        )
        return font_for_config(config, role, size=size)

    @classmethod
    def control_height(
        cls,
        minimum: int = 28,
        role: FontRole | str = FontRole.UI,
        padding: int = 10,
    ) -> int:
        """返回适配当前字体的安全控件高度。"""

        return max(minimum, QFontMetrics(cls.font_for_role(role)).height() + padding)

    @classmethod
    def get_default_font(cls, size: int | None = None) -> QFont:
        """创建界面字体；保留对旧版可写类属性的兼容。"""

        font = QFont(
            cls.DEFAULT_FONT_FAMILY,
            cls.DEFAULT_FONT_SIZE if size is None else size,
        )
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return font

    @classmethod
    def get_log_font(cls) -> QFont:
        """创建日志等宽字体；保留旧版方法名称。"""

        font = QFont(cls.LOG_FONT, cls.LOG_FONT_SIZE_VAR)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return font


def get_default_font(size: int | None = None) -> QFont:
    """返回默认界面字体。"""

    return FontMixin.get_default_font(size)


__all__ = [
    "DEFAULT_FONT_FAMILY",
    "FontConfig",
    "FontMixin",
    "FontRole",
    "LOG_FONT",
    "LOG_FONT_SIZE",
    "get_default_font",
]
