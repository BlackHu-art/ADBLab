"""在 GUI 启动时安装应用和组件翻译，保持业务数据与系统区域设置独立。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
from qfluentwidgets import FluentTranslator

from core.settings_manager import normalise_language
from gui.generated import translations_rc  # noqa: F401


def tr(text: str) -> str:
    """翻译应用界面源文案；缺少词条时保留原文。"""
    return QCoreApplication.translate("ADBLab", text)


def resolve_language(language: object, system_locale: QLocale | None = None) -> str:
    """将设置解析到可用资源语言，不修改 Qt 默认区域或进程环境。"""
    selected = normalise_language(language)
    if selected != "Auto":
        return selected
    locale = system_locale if system_locale is not None else QLocale.system()
    if locale.language() != QLocale.Language.Chinese:
        return "en_US"
    if locale.script() == QLocale.Script.TraditionalHanScript or locale.territory() in (
        QLocale.Country.HongKong, QLocale.Country.Macao, QLocale.Country.Taiwan,
    ):
        return "zh_HK"
    return "zh_CN"


def install_translators(
    app: QCoreApplication, language: object,
) -> tuple[QTranslator, ...]:
    """在主线程首次创建页面前安装翻译，返回需保留至事件循环退出的对象。

    QObject 所有权归应用；Qt 和 Fluent 的英文源文案不要求非空翻译资源。
    应用词库缺失时记录诊断并保留源文案，不阻止启动。
    """
    resolved = resolve_language(language)
    installed: list[QTranslator] = []
    qt_translator = QTranslator(app)
    # Qt 将繁体中文资源命名为 zh_TW，应用和 Fluent 使用 Gallery 的 zh_HK。
    qt_locale = QLocale("zh_TW" if resolved == "zh_HK" else resolved)
    if qt_translator.load(
        qt_locale, "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
    ) and app.installTranslator(qt_translator):
        installed.append(qt_translator)

    fluent_translator = FluentTranslator(QLocale(resolved), app)
    if app.installTranslator(fluent_translator):
        installed.append(fluent_translator)

    # 历史页面同时使用中文和英文源文案，简中也须安装应用词库，不能依赖源文案回退。
    app_translator = QTranslator(app)
    if app_translator.load(f":/adblab/i18n/adblab.{resolved}.qm"):
        if app.installTranslator(app_translator):
            installed.append(app_translator)
    else:
        logging.getLogger(__name__).warning(
            "Application translation for %s is unavailable; using source text", resolved,
        )
    return tuple(installed)
