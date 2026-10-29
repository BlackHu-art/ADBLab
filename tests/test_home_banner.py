"""首页全宽横幅在主题、字体和滚动状态下的可观察布局契约。"""

from hashlib import sha256
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QLayout, QWidget
from shiboken6 import isValid

from core.settings_manager import AppSettings
from gui.pages.fluent_pages import ActionCard, ActionCardView, HomePage
from gui.styles import BaseStyles
from gui.widgets.home_banner import HomeBanner
from models.device_store import DeviceStore
from tests.test_accessibility_contract import _contrast_ratio
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.test_navigation_rendering import _mica_content_color
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)
from utils.resource_path import resource_path


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


def test_home_banner_asset_preserves_reference_original():
    path = Path(resource_path("resources/images/gallery_header.png"))
    assert sha256(path.read_bytes()).hexdigest() == (
        "f372b0da602d18b8d8ed3c1c824eafc5522d80504842c31523836cb67867d0b9"
    )
    source = QImage(str(path))
    assert source.size() == QSize(1921, 1203)
    assert source.hasAlphaChannel()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_home_banner_preserves_original_pixels_in_both_material_modes(
    qt_application, home_settings, monkeypatch, tmp_path, theme,
):
    """云母只改变透明区域的底色，不能冲淡原图中不透明的图案。"""
    BaseStyles.switch_theme(theme)
    source = QImage(16, 16, QImage.Format.Format_RGB32)
    source.fill(QColor("#5130A5"))
    image_path = tmp_path / "resources" / "images" / "gallery_header.png"
    image_path.parent.mkdir(parents=True)
    assert source.save(str(image_path))
    monkeypatch.setattr(import_module("utils.resource_path"), "_base_dir", lambda: str(tmp_path))
    host = QWidget()
    active = [False]
    host.isMicaEffectEnabled = lambda: active[0]
    host.setAutoFillBackground(True)
    content = QWidget()
    banner = HomeBanner(content, host)
    banner.setGeometry(0, 0, 180, 120)
    content.hide()
    host.resize(180, 120)
    host.show()
    try:
        for mica in (False, True, False, True):
            active[0] = mica
            colors = []
            for backdrop in (QColor("#DCE5EF"), QColor("#E8E2DC")):
                palette = host.palette()
                palette.setColor(host.backgroundRole(), backdrop)
                host.setPalette(palette)
                host.update()
                qt_application.processEvents()
                image = host.grab().toImage()
                scale = image.devicePixelRatio()
                colors.append(image.pixelColor(round(90 * scale), round(10 * scale)))
            assert colors == [QColor("#5130A5"), QColor("#5130A5")]
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_home_cards_follow_host_mica_without_losing_input_state(
    qt_application, home_settings, theme,
):
    """卡片按实际宿主低覆盖着色；开关材质不触发动作，鼠标和键盘入口保持。"""
    BaseStyles.switch_theme(theme)
    host = QWidget()
    active = [False]
    host.isMicaEffectEnabled = lambda: active[0]
    host.setAutoFillBackground(True)
    backdrop = QColor("#DCE5EF" if theme == "Light" else "#252B32")
    palette = host.palette()
    palette.setColor(host.backgroundRole(), backdrop)
    host.setPalette(palette)
    activated = Mock()
    card = ActionCard("", "示例", "输入和导航保持原状", activated, host)
    card.setGeometry(10, 10, 330, 100)
    host.resize(360, 150)
    host.show()
    try:
        QTest.mouseMove(host, QPoint(350, 140))
        for mica in (True, False, True):
            active[0] = mica
            host.update()
            qt_application.processEvents()
            wait_until(qt_application, lambda: (
                card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
            ))
            image = host.grab().toImage()
            scale = image.devicePixelRatio()
            actual = image.pixelColor(round(20 * scale), round(100 * scale))
            if mica and theme == "Light":
                assert actual == _mica_content_color(backdrop, "Light")
            elif not mica:
                native = QColor(255, 255, 255, 170 if theme == "Light" else 13)
                assert card.backgroundColor == native
            activated.assert_not_called()
        for switched_theme in ("Dark" if theme == "Light" else "Light", theme):
            BaseStyles.switch_theme(switched_theme)
            host.update()
            qt_application.processEvents()
            expected = QColor(255, 255, 255, 64 if switched_theme == "Light" else 13)
            wait_until(qt_application, lambda: (
                card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
                and card.backgroundColor == expected
            ))
            activated.assert_not_called()
        normal = card.backgroundColor
        QTest.mouseMove(card, QPoint(200, 80))
        wait_until(qt_application, lambda: (
            card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped and card.isHover
        ))
        hovered = card.backgroundColor
        assert hovered != normal
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(200, 80))
        wait_until(qt_application, lambda: (
            card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped and card.isPressed
        ))
        assert card.backgroundColor != hovered
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(-1, -1))
        activated.assert_not_called()
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Return)
        activated.assert_called_once_with()
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_banner_card_text_remains_readable_over_original_artwork(
    qt_application, home_settings, theme,
):
    """完整原图可包含黑白色块，卡片三个交互态仍须保留文字对比度。"""
    BaseStyles.switch_theme(theme)
    host = QWidget()
    host.isMicaEffectEnabled = lambda: True
    content = QWidget()
    banner = HomeBanner(content, host)
    content.hide()
    card = ActionCard("", "标题", "说明", lambda: None, banner)
    card.setGeometry(30, 30, 300, 100)
    banner.resize(360, 180)
    host.resize(400, 220)
    host.show()
    try:
        for state in ("normal", "hover", "pressed"):
            if state == "normal":
                QTest.mouseMove(host, QPoint(390, 210))
            elif state == "hover":
                QTest.mouseMove(card, QPoint(200, 80))
            else:
                QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(200, 80))
            wait_until(qt_application, lambda: (
                card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
            ))
            for color in (QColor("black"), QColor("white")):
                image = QImage(1, 1, QImage.Format.Format_RGB32)
                image.fill(color)
                painter = QPainter(image)
                painter.fillRect(image.rect(), card.backgroundColor)
                painter.end()
                assert _contrast_ratio(
                    BaseStyles.color("TEXT_PRIMARY"), image.pixelColor(0, 0).name(),
                ) >= 4.5, (theme, state, color.name(), card.backgroundColor.name())
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(-1, -1))
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("move_group", [False, True])
def test_action_card_refreshes_artwork_surface_when_reparented_in_same_window(
    qt_application, home_settings, theme, move_group,
):
    """同窗移动卡片或其分组后，首次显示就应使用新背景所需的文字对比底色。"""
    BaseStyles.switch_theme(theme)
    host = QWidget()
    host.isMicaEffectEnabled = lambda: True
    host.resize(800, 500)
    plain = QWidget(host)
    plain.setGeometry(0, 0, 360, 300)
    banner = HomeBanner(QWidget(), host)
    banner.setGeometry(380, 0, 360, 300)
    host.show()
    QTest.mouseMove(host, QPoint(790, 490))
    group = QWidget(plain)
    card = ActionCard("", "标题", "说明", lambda: None, group)
    card.resize(300, 100)
    group.resize(320, 120)
    group.show()
    card.show()
    moving = group if move_group else card
    generic = QColor(255, 255, 255, 64 if theme == "Light" else 13)
    artwork = QColor(255, 255, 255, 170) if theme == "Light" else QColor(0, 0, 0, 160)
    try:
        assert not card.isHover
        assert card.backgroundColor == generic
        for parent, expected in ((banner, artwork), (plain, generic), (banner, artwork)):
            moving.setParent(parent)
            moving.show()
            qt_application.processEvents()
            assert not card.isHover
            assert card.backgroundColor == expected, (theme, move_group, parent)
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_home_initial_show_refreshes_cards_wrapped_into_banner(
    qt_application, home_settings, theme,
):
    """首页先创建快捷分组再包入横幅，不依赖 MainFrame 后续全局刷新纠正底色。"""
    BaseStyles.switch_theme(theme)
    host = QWidget()
    host.isMicaEffectEnabled = lambda: True
    host.resize(1200, 800)
    host.show()
    QTest.mouseMove(host, QPoint(1190, 790))
    page = HomePage(_frame(), host)
    page.resize(900, 700)
    page.show()
    try:
        wait_for_stable_geometry(qt_application, (page, page.banner, *page.tool_cards.values()))
        expected = QColor(255, 255, 255, 170) if theme == "Light" else QColor(0, 0, 0, 160)
        banner_cards = page.banner.findChildren(ActionCard)
        assert len(banner_cards) == 6
        for card in banner_cards:
            assert not card.isHover
            assert card.backgroundColor == expected
        outside_card = page.tool_cards["save_path"]
        assert not outside_card.isHover
        assert outside_card.backgroundColor == QColor(255, 255, 255, 64 if theme == "Light" else 13)
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.0])
@pytest.mark.parametrize("height", [40, 120])
def test_home_banner_renders_original_pixels_at_device_resolution(
    qt_application, home_settings, monkeypatch, tmp_path, scale, height,
):
    """原图恰好覆盖设备像素时应保留逐列细节，不能先缩到逻辑像素再放大。"""
    source = QImage(round(128 * scale), round(height * scale), QImage.Format.Format_RGB32)
    for x in range(source.width()):
        for y in range(source.height()):
            source.setPixelColor(x, y, QColor("white" if (x + y) % 2 else "black"))
    image_path = tmp_path / "resources" / "images" / "gallery_header.png"
    image_path.parent.mkdir(parents=True)
    assert source.save(str(image_path))
    monkeypatch.setattr(import_module("utils.resource_path"), "_base_dir", lambda: str(tmp_path))
    content = QWidget()
    banner = HomeBanner(content)
    # 此处单独验证绘制，避免布局留白把 40px 测试画布撑到 64px。
    banner.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    content.hide()
    banner.resize(128, height)
    rendered = QImage(
        source.width(), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied,
    )
    rendered.setDevicePixelRatio(scale)
    rendered.fill(Qt.GlobalColor.transparent)
    banner.render(rendered, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
    assert banner.size() == QSize(128, height)
    assert rendered.convertToFormat(QImage.Format.Format_RGB32) == source
    banner.deleteLater()


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.0])
@pytest.mark.parametrize("height", [40, 120])
def test_home_banner_keeps_all_image_landmarks_when_aspect_ratio_changes(
    qt_application, home_settings, monkeypatch, tmp_path, scale, height,
):
    """参考横幅完整映射原图；不同长宽比下四个象限都不能被裁掉或留空。"""
    source = QImage(256, 160, QImage.Format.Format_RGB32)
    colors = (QColor("red"), QColor("green"), QColor("blue"), QColor("yellow"))
    for y in range(source.height()):
        for x in range(source.width()):
            source.setPixelColor(x, y, colors[(y >= 80) * 2 + (x >= 128)])
    image_path = tmp_path / "resources" / "images" / "gallery_header.png"
    image_path.parent.mkdir(parents=True)
    assert source.save(str(image_path))
    monkeypatch.setattr(import_module("utils.resource_path"), "_base_dir", lambda: str(tmp_path))
    content = QWidget()
    banner = HomeBanner(content)
    banner.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    content.hide()
    banner.resize(128, height)
    rendered = QImage(
        round(128 * scale), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied,
    )
    rendered.setDevicePixelRatio(scale)
    rendered.fill(Qt.GlobalColor.transparent)
    banner.render(rendered, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
    assert banner.size() == QSize(128, height)
    for index, (x, y) in enumerate(((.1, .1), (.9, .1), (.1, .9), (.9, .9))):
        assert rendered.pixelColor(
            round(rendered.width() * x), round(rendered.height() * y),
        ) == colors[index]
    banner.deleteLater()


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
    cards = page.banner.findChildren(ActionCard)
    wait_for_stable_geometry(qt_application, (page, banner, *cards))

    assert mapped_rect(banner, page.viewport()).topLeft() == QPoint(0, 0)
    assert banner.width() == page.viewport().width()
    assert page.horizontalScrollBar().maximum() == 0
    tools = banner.findChild(ActionCardView)
    assert mapped_rect(tools, banner).topLeft() == QPoint(32, 24)
    assert not any(label.text() == "ADBLab" for label in page.findChildren(QLabel))
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
    assert page.tool_cards["save_path"] in workspace_cards
    assert workspace_cards[-1] is page.tool_cards["save_path"]
    assert not banner.isAncestorOf(page.tool_cards["save_path"])
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
    tools = page.banner.findChild(ActionCardView)
    assert tools.title_label.font().pointSizeF() == 22
    for card in cards.values():
        assert_scroll_target_reachable(page, card)
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Return)
    assert frame._open_workspace_feature.call_args_list == [
        call("apps", "manager"),
        call("devices", "files"),
        call("devices", "remote"),
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


def test_home_banner_repaints_for_theme_preserves_image_colors_and_survives_destruction(
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
        BaseStyles.set_accent_color("#bd3068")
        qt_application.processEvents()
        accent_pixel = banner.grab().toImage().pixelColor(banner.width() - 20, 12)
        assert accent_pixel == dark_pixel
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
                    lambda: frame._page_transition.animation.state()
                    == QAbstractAnimation.State.Stopped,
                )
                frame._on_nav_requested("home")
                wait_until(
                    qt_application,
                    lambda: frame._page_transition.animation.state()
                    == QAbstractAnimation.State.Stopped
                    and frame.navigationInterface.panel.expandAni.state()
                    == QAbstractAnimation.State.Stopped,
                )
                page = frame._home_page
                cards = page.banner.findChildren(ActionCard)
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
        assert page.viewport().mask().boundingRect() == page.viewport().rect()
        assert not page.viewport().mask().contains(QPoint(0, 0))
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
