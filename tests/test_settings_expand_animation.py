"""设置页展开卡的中间帧布局回归，隔离本地 ADB 与持久化。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLabel

from core.adb_runtime import RuntimeSnapshot
from core.settings_manager import DEFAULTS, AppSettings
from gui.i18n import install_translators
from gui.pages.fluent_pages import SettingsPage
from gui.styles import BaseStyles
from gui.widgets import adb_client_card as cards
from services.adb_clients import ClientProbe
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry
from utils.adb_resolver import AdbCandidate

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width,font_size", [(978, 12), (420, 12), (978, 22), (420, 22)])
def test_auto_client_summary_stays_inside_header(qt_application, make_page, width, font_size):
    page = make_page(width=width, font_size=font_size)
    card = page.adb_client_card
    path = "C:/fixture/adb.exe"
    card._on_effective_path_ready(card._generation, path)
    card.apply_probes([ClientProbe("bundled", path, True, True, "1.0.41 (37.0.0)")])
    page.ensureWidgetVisible(card, 0, 0)
    _settle(qt_application, page)
    label = card.card.contentLabel
    assert "应用自带" in label.text()
    assert "1.0.41 (37.0.0)" in label.text()
    assert label.toolTip() == path
    assert card.card.rect().contains(mapped_rect(label, card.card))
    assert mapped_rect(label, card.card).right() < card.card.expandButton.x()
    assert card.rect().contains(mapped_rect(card.card.expandButton, card))
    assert page.viewport().rect().contains(mapped_rect(card, page.viewport()))


@pytest.fixture
def make_page(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [
        AdbCandidate("bundled", "C:/fixture/adb.exe"),
    ])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    pages = []
    translators = []

    def build(width=978, font_size=12, language="zh_CN"):
        values = dict(DEFAULTS, font_family="Microsoft YaHei UI", ui_font_size=font_size)
        settings = SimpleNamespace(get=values.get)
        monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
        BaseStyles.reload_from_settings()
        translators.extend(install_translators(qt_application, language))
        frame = Mock()
        frame._always_on_top = False
        page = SettingsPage(frame)
        page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        pages.append(page)
        page.resize(width, 640)
        page.show()
        _settle(qt_application, page)
        return page

    yield build
    for page in pages:
        page.close()
    for translator in reversed(translators):
        qt_application.removeTranslator(translator)
        translator.deleteLater()


def _settle(app, page):
    wait_for_stable_geometry(app, (
        page, page.widget(), page.adb_client_card, page.adb_check_card,
        page.adb_client_card.parentWidget(), page.restart_adb_card, page.about_panel,
    ))


def _start_toggle(app, page, card):
    button = card.card.expandButton
    page.ensureWidgetVisible(button, 0, 0)
    app.processEvents()
    assert button.isVisibleTo(page)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    card.expandAni.pause()
    card.card.expandButton.rotateAni.pause()


def _geometry(page):
    return (
        page.adb_client_card.height() + page.adb_check_card.height(),
        page.adb_client_card.parentWidget().height(),
        page.about_panel.y(),
        page.widget().height(),
        page.verticalScrollBar().maximum(),
    )


def _assert_tracks_cards(page, baseline):
    current = _geometry(page)
    growth = current[0] - baseline[0]
    # 子卡、父分组、下方内容与滚动范围必须在当前帧同步，不能只检查动画终态。
    assert all(value - before == growth for value, before in zip(current[1:], baseline[1:])), (
        baseline, current,
    )
    group = page.adb_client_card.parentWidget()
    assert page.restart_adb_card.geometry().bottom() < group.height()
    assert page.adb_client_card.geometry().bottom() < page.adb_check_card.y()
    assert page.adb_check_card.geometry().bottom() < page.restart_adb_card.y()
    assert page.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
@pytest.mark.parametrize("width,font_size", [(978, 12), (420, 22)])
@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
def test_expanding_and_collapsing_cards_move_page_on_every_frame(
    qt_application, make_page, card_name, width, font_size, language,
):
    page = make_page(width, font_size, language)
    card = getattr(page, card_name)
    baseline = _geometry(page)
    for expanded in (True, False):
        _start_toggle(qt_application, page, card)
        assert card.isExpand is expanded
        heights = []
        for time_ms in (0, 40, 80, 120, 160, card.expandAni.duration()):
            card.expandAni.setCurrentTime(time_ms)
            _settle(qt_application, page)
            _assert_tracks_cards(page, baseline)
            heights.append(card.height())
        if expanded:
            assert heights[0] < heights[1] < heights[-1]
            for row in card.widgets:
                # 验证实际选项文字和操作，不把原生边框覆盖的行尾留白视为裁切。
                for control in row.findChildren(QLabel) + row.findChildren(QAbstractButton):
                    assert card.viewport().rect().contains(mapped_rect(control, card.viewport())), (
                        control.text(), control.minimumSize(), control.minimumSizeHint(),
                        control.sizePolicy().horizontalPolicy(), row.minimumSize(),
                        row.minimumSizeHint(), row.layout().minimumSize(),
                        row.layout().geometry(), row.geometry(),
                    )
        else:
            assert heights[0] > heights[1] > heights[-1]
    assert _geometry(page) == baseline


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
def test_interrupted_animation_keeps_group_and_following_content_in_sync(
    qt_application, make_page, card_name,
):
    page = make_page()
    card = getattr(page, card_name)
    baseline = _geometry(page)
    for time_ms in (80, 40, 120, card.expandAni.duration()):
        _start_toggle(qt_application, page, card)
        card.expandAni.setCurrentTime(time_ms)
        _settle(qt_application, page)
        _assert_tracks_cards(page, baseline)
    assert not card.isExpand
    assert _geometry(page) == baseline


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
def test_status_reflow_during_animation_keeps_subsequent_frames_in_sync(
    qt_application, make_page, card_name,
):
    page = make_page()
    card = getattr(page, card_name)
    baseline = _geometry(page)
    _start_toggle(qt_application, page, card)
    card.expandAni.setCurrentTime(80)
    page.update_adb_environment(RuntimeSnapshot(
        False, True, False, True, 0, 0, status="ready",
    ))
    _settle(qt_application, page)
    _assert_tracks_cards(page, baseline)
    for time_ms in (120, 160, card.expandAni.duration()):
        card.expandAni.setCurrentTime(time_ms)
        _settle(qt_application, page)
        _assert_tracks_cards(page, baseline)


def test_candidate_refresh_during_animation_keeps_new_content_inside_group(
    qt_application, make_page,
):
    page = make_page()
    card = page.adb_client_card
    baseline = _geometry(page)
    _start_toggle(qt_application, page, card)
    card.expandAni.setCurrentTime(80)
    card._on_probes(card._generation, [
        AdbCandidate("bundled", "C:/fixture/adb.exe"),
        AdbCandidate("PATH", "C:/other/adb.exe"),
    ], [
        ClientProbe("bundled", "C:/fixture/adb.exe", True, True, "1.0.41"),
        ClientProbe("PATH", "C:/other/adb.exe", True, True, "1.0.41"),
    ])
    _settle(qt_application, page)
    _assert_tracks_cards(page, baseline)
    for time_ms in (120, 160, card.expandAni.duration()):
        card.expandAni.setCurrentTime(time_ms)
        _settle(qt_application, page)
        _assert_tracks_cards(page, baseline)
    assert card.client_button("PATH").isEnabled()
    _start_toggle(qt_application, page, card)
    card.expandAni.setCurrentTime(card.expandAni.duration())
    _settle(qt_application, page)
    assert _geometry(page) == baseline
