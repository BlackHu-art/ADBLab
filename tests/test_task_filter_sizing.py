"""任务筛选按全部选项稳定排布，弹层内容与按钮同宽。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint
from PySide6.QtTest import QSignalSpy
from shiboken6 import isValid

from core.settings_manager import AppSettings
from gui.i18n import install_translators
from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles
from tests.ui_geometry_helpers import assert_text_fits, wait_for_stable_geometry, wait_until


@pytest.fixture
def make_filter_page(qt_application, monkeypatch):
    pages, installed = [], []

    def create(language="zh_CN", font_size=12, width=700):
        settings = {"ui_font_size": font_size, "font_family": "Arial", "log_font_size": 11}
        monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
        BaseStyles.reload_from_settings()
        installed.extend(install_translators(qt_application, language))
        page = TaskCenterPage()
        pages.append(page)
        page.move(0, 0)
        page.resize(width, 650)
        page.show()
        page.activateWindow()
        wait_until(qt_application, page.isActiveWindow)
        wait_for_stable_geometry(qt_application, (page, page.filters))
        return page

    yield create
    for page in pages:
        page.shutdown()
        page.close()
        page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for translator in installed:
        qt_application.removeTranslator(translator)


@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
@pytest.mark.parametrize("font_size", [12, 22])
def test_selection_keeps_filter_and_search_geometry_stable(
    qt_application,
    make_filter_page,
    language,
    font_size,
):
    page = make_filter_page(language, font_size)
    geometry = tuple(
        widget.geometry() for widget in (page.search_edit, page.state_combo, page.kind_combo)
    )
    for combo in (page.state_combo, page.kind_combo):
        for index in range(combo.count()):
            combo.setCurrentIndex(index)
            wait_for_stable_geometry(qt_application, (page.filters, combo))
            assert (
                tuple(
                    widget.geometry()
                    for widget in (
                        page.search_edit,
                        page.state_combo,
                        page.kind_combo,
                    )
                )
                == geometry
            )
            assert combo.text() == combo.currentText()
            assert_text_fits(combo)


@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
def test_popup_visual_panel_matches_filter_button(qt_application, make_filter_page, language):
    page = make_filter_page(language)
    for combo in (page.state_combo, page.kind_combo):
        combo._showComboMenu()
        menu = combo.dropMenu
        try:
            wait_until(
                qt_application,
                lambda: menu.aniManager.ani.state() == QAbstractAnimation.State.Stopped,
            )
            # 外层包含阴影留白，实际内容面板才与按钮对齐。
            assert abs(menu.view.width() - combo.width()) <= 1
            panel_left = menu.view.mapToGlobal(QPoint()).x()
            button_left = combo.mapToGlobal(QPoint()).x()
            assert abs(panel_left - button_left) <= 1
        finally:
            if isValid(menu):
                menu.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("width", [220, 360, 700])
def test_filter_resize_preserves_values_and_fits_current_viewport(
    qt_application,
    make_filter_page,
    width,
):
    page = make_filter_page("en_US", 22)
    page.state_combo.setCurrentIndex(page.state_combo.findData("partial"))
    page.kind_combo.setCurrentIndex(page.kind_combo.findData("performance"))
    state_changed = QSignalSpy(page.state_combo.currentIndexChanged)
    kind_changed = QSignalSpy(page.kind_combo.currentIndexChanged)
    page.resize(width, 650)
    wait_for_stable_geometry(qt_application, (page, page.filters, page.state_combo))
    for combo in (page.state_combo, page.kind_combo):
        assert page.filters.rect().contains(combo.geometry())
        assert_text_fits(combo)
    assert page.state_combo.currentData() == "partial"
    assert page.kind_combo.currentData() == "performance"
    assert state_changed.count() == kind_changed.count() == 0
    assert page._scroll.horizontalScrollBar().maximum() == 0


def test_filter_font_round_trip_keeps_values_and_restores_compact_size(
    qt_application,
    make_filter_page,
):
    page = make_filter_page()
    page.kind_combo.setCurrentIndex(page.kind_combo.findData("shell"))
    controls = (page.search_edit, page.state_combo, page.kind_combo)
    initial = tuple(control.size() for control in controls)
    settings = AppSettings.instance()
    for size in (22, 12):
        settings["ui_font_size"] = size
        BaseStyles.reload_from_settings()
        wait_for_stable_geometry(qt_application, (page, page.filters))
        assert len({control.height() for control in controls}) == 1
        assert page.kind_combo.currentData() == "shell"
        if size == 12:
            assert tuple(control.size() for control in controls) == initial
