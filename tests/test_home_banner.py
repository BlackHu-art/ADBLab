"""首页全宽横幅在主题、字体和滚动状态下的可观察布局契约。"""

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from shiboken6 import isValid

from core.settings_manager import AppSettings
from gui.pages.fluent_pages import ActionCard, ActionCardView, HomePage
from gui.styles import BaseStyles, FontRole
from models.device_store import DeviceStore
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)


@pytest.fixture
def home_settings(monkeypatch, qt_application):
    values = {"font_family": "Microsoft YaHei", "ui_font_size": 12, "log_font_size": 9}
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda cls: SimpleNamespace(get=values.get))
    )
    BaseStyles.reload_from_settings()
    return values


def _frame(*, standalone=False):
    frame = SimpleNamespace(
        _on_nav_requested=Mock(),
        _request_device_refresh=Mock(),
        _open_workspace_feature=Mock(),
        _open_cmd=Mock(),
        _on_save_path_clicked=Mock(),
    )
    if not standalone:
        frame._global_device_bar = object()
    return frame


class _PaintObserver(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return super().eventFilter(watched, event)


@pytest.mark.parametrize("width,font_size", [(1220, 12), (640, 12), (420, 22), (300, 22)])
def test_home_banner_spans_page_and_keeps_wrapped_cards_inside(
    qt_application, home_settings, width, font_size,
):
    home_settings["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page = HomePage(_frame())
    page.resize(width, 650)
    page.show()
    banner = page.banner
    cards = list(page.tool_cards.values())
    wait_for_stable_geometry(qt_application, (page, banner, *cards))

    assert mapped_rect(banner, page.viewport()).topLeft() == QPoint(0, 0)
    assert banner.width() == page.viewport().width()
    assert page.horizontalScrollBar().maximum() == 0
    assert banner.title_label.mapTo(banner, QPoint()).x() == 32
    assert banner.title_label.font() == BaseStyles.font_for_role(FontRole.TITLE)
    first_row = [card for card in cards if card.y() == cards[0].y()]
    assert min(mapped_rect(card, banner).left() for card in cards) == 32
    row_right = max(mapped_rect(card, banner).right() for card in first_row)
    assert 32 <= banner.width() - row_right - 1 <= 36
    for card in cards:
        assert banner.rect().contains(mapped_rect(card, banner))
        for label in (card.title_label, card.content_label):
            assert label.height() >= label.heightForWidth(label.width())
            assert card.rect().contains(mapped_rect(label, card))
        assert_scroll_target_reachable(page, card)

    workspace = next(
        group for group in page.findChildren(ActionCardView)
        if not banner.isAncestorOf(group)
    )
    workspace_cards = workspace.findChildren(ActionCard)
    assert min(mapped_rect(card, page.widget()).left() for card in workspace_cards) == 32
    assert_scroll_target_reachable(page, workspace_cards[-1])


def test_home_banner_height_follows_width_and_scrolls_with_page(
    qt_application, home_settings,
):
    page = HomePage(_frame())
    page.resize(1220, 920)
    page.show()
    cards = list(page.tool_cards.values())
    wait_for_stable_geometry(qt_application, (page, page.banner, *cards))
    wide_height = page.banner.height()
    assert page.verticalScrollBar().maximum() == 0

    page.resize(420, 550)
    wait_until(qt_application, lambda: page.banner.height() > wide_height)
    assert page.verticalScrollBar().maximum() > 100
    page.verticalScrollBar().setValue(100)
    assert page.banner.mapTo(page.viewport(), QPoint()).y() == -100
    assert_scroll_target_reachable(page, cards[-1])

    page.resize(1220, 920)
    wait_until(qt_application, lambda: page.verticalScrollBar().maximum() == 0)
    assert page.banner.height() == wide_height


def test_home_banner_font_change_preserves_shortcut_focus_and_routes(
    qt_application, home_settings,
):
    frame = _frame()
    page = HomePage(frame)
    page.resize(420, 650)
    page.show()
    cards = dict(page.tool_cards)
    page.tool_cards["file_explorer"].setFocus()
    qt_application.processEvents()
    previous_height = page.banner.height()
    home_settings["ui_font_size"] = 22
    BaseStyles.reload_from_settings()
    wait_until(qt_application, lambda: page.banner.height() > previous_height)
    assert page.tool_cards == cards
    assert cards["file_explorer"].hasFocus()
    assert page.banner.title_label.font() == BaseStyles.font_for_role(FontRole.TITLE)
    for card in cards.values():
        assert_scroll_target_reachable(page, card)
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Return)
    assert frame._open_workspace_feature.call_args_list == [
        call("apps", "manager"),
        call("devices", "files"),
        call("system", "logcat"),
        call("system", "performance"),
    ]
    frame._open_cmd.assert_called_once_with()
    frame._on_save_path_clicked.assert_called_once_with()


def test_home_standalone_device_context_retains_inner_spacing_and_actions(
    qt_application, home_settings,
):
    frame = _frame(standalone=True)
    page = HomePage(frame)
    page.set_device_context([], [], "empty")
    page.resize(820, 700)
    page.show()
    wait_for_stable_geometry(qt_application, (page, page.device_context))
    assert page.device_context.isVisibleTo(page)
    assert mapped_rect(page.device_context, page.widget()).left() == 32
    assert page.widget().width() - mapped_rect(page.device_context, page.widget()).right() - 1 == 32
    page.device_context.manage_button.click()
    frame._on_nav_requested.assert_called_once_with("devices")


def test_home_banner_repaints_for_theme_accent_and_survives_parent_destruction(
    qt_application, home_settings,
):
    original_accent = BaseStyles.accent_color()
    page = HomePage(_frame())
    page.resize(900, 700)
    page.show()
    banner = page.banner
    wait_for_stable_geometry(qt_application, (page, banner))
    observer = _PaintObserver(banner)
    banner.installEventFilter(observer)
    try:
        BaseStyles.switch_theme("Light")
        light_pixel = banner.grab().toImage().pixelColor(banner.width() - 20, 12)
        paint_count = observer.count
        BaseStyles.switch_theme("Dark")
        wait_until(qt_application, lambda: observer.count > paint_count)
        dark_pixel = banner.grab().toImage().pixelColor(banner.width() - 20, 12)
        assert light_pixel != dark_pixel
        paint_count = observer.count
        BaseStyles.set_accent_color("#bd3068")
        wait_until(qt_application, lambda: observer.count > paint_count)
        accent_pixel = banner.grab().toImage().pixelColor(banner.width() - 20, 12)
        assert accent_pixel != dark_pixel
        banner.set_top_left_radius(10)
        rounded = banner.grab().toImage()
        banner.set_top_left_radius(0)
        square = banner.grab().toImage()
        assert rounded.pixelColor(0, 0) != square.pixelColor(0, 0)
        assert rounded.pixelColor(banner.width() - 1, 0) == square.pixelColor(banner.width() - 1, 0)
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(banner)
        BaseStyles.switch_theme("Light")
        BaseStyles.set_accent_color(original_accent)
        BaseStyles.ui_font_changed.emit(BaseStyles.current_font_config())
        qt_application.processEvents()
    finally:
        BaseStyles.set_accent_color(original_accent)


def test_home_banner_uses_resolved_dark_palette_when_following_system(
    qt_application, home_settings, monkeypatch,
):
    BaseStyles.switch_theme("Dark")
    page = HomePage(_frame())
    page.resize(900, 700)
    page.show()
    wait_for_stable_geometry(qt_application, (page, page.banner))
    explicit_dark = page.banner.grab().toImage().pixelColor(20, 12)
    monkeypatch.setattr("gui.styles.theme._theme_mode", "System")
    assert BaseStyles.resolved_theme() == "Dark"
    system_dark = page.banner.grab().toImage().pixelColor(20, 12)
    assert system_dark == explicit_dark


def test_main_window_home_retains_all_shortcuts_after_hidden_resize_and_theme_change(
    qt_application, monkeypatch,
):
    settings = _MainFrameSettings()
    settings.values.update(theme="Light", mica_enabled=False)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda devices: [])
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("test", QSize(1920, 1080))),
    )
    try:
        frame.show()
        for theme in ("Light", "Dark"):
            BaseStyles.switch_theme(theme)
            for width in (1120, 860, 1120):
                frame._on_nav_requested("settings")
                frame.resize(width, 720)
                wait_until(
                    qt_application,
                    lambda: frame.stackedWidget.view._ani.state()
                    == QAbstractAnimation.State.Stopped,
                )
                frame._on_nav_requested("home")
                wait_until(
                    qt_application,
                    lambda: frame.stackedWidget.view._ani.state()
                    == QAbstractAnimation.State.Stopped
                    and frame.navigationInterface.panel.expandAni.state()
                    == QAbstractAnimation.State.Stopped,
                )
                page = frame._home_page
                cards = list(page.tool_cards.values())
                wait_for_stable_geometry(qt_application, (frame, page, page.banner, *cards))
                for card in cards:
                    assert page.banner.rect().contains(mapped_rect(card, page.banner)), (
                        theme, width, card.accessibleName(), page.banner.geometry(),
                        mapped_rect(card, page.banner),
                    )
                    assert_scroll_target_reachable(page, card)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_home_viewport_keeps_mica_corner_clear_while_content_scrolls_and_resizes(
    qt_application, monkeypatch, theme,
):
    settings = _MainFrameSettings()
    settings.values.update(
        theme=theme, mica_enabled=True, window_width=860, window_height=500,
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda devices: [])
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("test", QSize(1920, 1080))),
    )
    backdrop = QColor("#315879")
    original_background = frame._normalBackgroundColor
    monkeypatch.setattr(
        frame, "_normalBackgroundColor",
        lambda: backdrop if frame.isMicaEffectEnabled() else original_background(),
    )
    try:
        frame.show()
        frame._on_nav_requested("home")
        BaseStyles.switch_theme(theme)
        page = frame._home_page
        for width in (860, 1120, 860):
            frame.resize(width, 500)
            wait_until(
                qt_application,
                lambda: frame.navigationInterface.panel.expandAni.state()
                == QAbstractAnimation.State.Stopped,
            )
            wait_for_stable_geometry(
                qt_application, (frame, page, page.banner, *page.tool_cards.values()),
            )
            assert page.viewport().mask().boundingRect() == page.viewport().rect()
            assert page.viewport().mask().contains(QPoint(page.viewport().width() - 1, 0))
            frame.backgroundColorAni.stop()
            frame.setBackgroundColor(backdrop)
            for scroll in (0, 50, page.verticalScrollBar().maximum()):
                page.verticalScrollBar().setValue(scroll)
                qt_application.processEvents()
                image = frame.grab().toImage()
                point = page.viewport().mapTo(frame, QPoint(0, 0))
                scale = image.devicePixelRatio()
                corner = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
                assert corner == backdrop, (theme, width, scroll, corner.name())

        frame.setMicaEffectEnabled(False)
        qt_application.processEvents()
        assert page.viewport().mask().isEmpty()
        page.verticalScrollBar().setValue(50)
        point = page.viewport().mapTo(frame, QPoint())
        image = frame.grab().toImage()
        scale = image.devicePixelRatio()
        corner = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
        assert corner != backdrop

        frame.setMicaEffectEnabled(True)
        frame.backgroundColorAni.stop()
        frame.setBackgroundColor(backdrop)
        qt_application.processEvents()
        point = page.viewport().mapTo(frame, QPoint())
        image = frame.grab().toImage()
        scale = image.devicePixelRatio()
        corner = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
        assert corner == backdrop
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
