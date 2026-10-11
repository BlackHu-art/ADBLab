"""静态图标缓存必须减少 SVG 解析，同时保持原生主题、缩放及绘制状态。"""

import sys
import threading
import weakref

import pytest
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtWidgets import QPushButton
from qfluentwidgets import FluentIcon, IconWidget, PrimaryPushButton, PushButton, Theme, ToolButton
from qfluentwidgets.common import icon as fluent_icons
from shiboken6 import isValid

from gui.styles import BaseStyles, icon_loader
from gui.styles.fluent import configure_button
from tests.test_settings_expand_animation import make_page as make_page

pytestmark = pytest.mark.ui


def _cached(icon):
    # 缓存尚未接入时仍走当前实际路径，以解析次数证明缺陷而非只检查新接口存在。
    return getattr(icon_loader, "cached_fluent_icon", lambda item: item)(icon)


def _render(icon, *, theme=Theme.LIGHT, ratio=1.0, angle=0.0, opacity=1.0, **attributes):
    image = QImage(round(48 * ratio), round(48 * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform,
        )
        painter.setOpacity(opacity)
        painter.translate(24, 24)
        painter.rotate(angle)
        painter.translate(-24, -24)
        icon.render(painter, QRectF(10.5, 11.5, 25, 23), theme=theme, **attributes)
    finally:
        painter.end()
    return image


@pytest.fixture
def svg_calls(monkeypatch, qt_application):
    cache = sys.modules.get("gui.styles.cached_icon")
    if cache is not None:
        cache.clear_icon_caches()
    constructors, rewrites, objects = [], [], []
    original_renderer = fluent_icons.QSvgRenderer
    original_write = fluent_icons.writeSvg

    def renderer(*args, **kwargs):
        constructors.append(threading.get_ident())
        result = original_renderer(*args, **kwargs)
        objects.append(weakref.ref(result))
        return result

    def write(*args, **kwargs):
        rewrites.append((args, kwargs))
        return original_write(*args, **kwargs)

    monkeypatch.setattr(fluent_icons, "QSvgRenderer", renderer)
    monkeypatch.setattr(fluent_icons, "writeSvg", write)
    if cache is not None:
        monkeypatch.setattr(cache, "QSvgRenderer", renderer)
    yield constructors, rewrites, objects
    if cache is not None:
        cache.clear_icon_caches()


@pytest.mark.parametrize("source", [FluentIcon.SETTING, icon_loader.DEVICE_ICON])
def test_repeated_paints_parse_static_svg_once(svg_calls, source):
    icon = _cached(source)
    images = [_render(icon) for _ in range(6)]
    assert all(image == images[0] for image in images)
    assert len(svg_calls[0]) == 1, "同一个静态图标仍在每次绘制时解析 SVG"


def test_tinted_arrow_reuses_xml_and_renderer_until_color_changes(svg_calls):
    arrow = _cached(FluentIcon.ARROW_DOWN)
    for angle in (0, 30, 70, 120, 180):
        _render(arrow, angle=angle, fill="#13579b")
    assert len(svg_calls[0]) == len(svg_calls[1]) == 1
    _render(arrow, fill="#ab3579")
    assert len(svg_calls[0]) == len(svg_calls[1]) == 2


@pytest.mark.parametrize("theme,ratio,angle,opacity", [
    (Theme.LIGHT, 1.0, 0.0, 1.0),
    (Theme.DARK, 1.5, 37.0, .3628),
    (Theme.LIGHT, 2.0, 180.0, .786),
])
def test_cached_vector_matches_native_pixels_with_dpi_rotation_and_opacity(
    qt_application, theme, ratio, angle, opacity,
):
    source = FluentIcon.ARROW_DOWN
    options = dict(theme=theme, ratio=ratio, angle=angle, opacity=opacity, fill="#0078d4")
    expected = _render(source, **options)
    actual = _render(_cached(source), **options)
    assert actual == expected


def test_cached_qicon_follows_live_theme_and_keeps_native_modes(qt_application):
    source = FluentIcon.SETTING
    native, cached = source.qicon(), _cached(source).qicon()
    for theme in ("Light", "Dark", "Light"):
        BaseStyles.switch_theme(theme)
        for ratio in (1.0, 1.5, 2.0):
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled, QIcon.Mode.Selected):
                expected = native.pixmap(QSize(24, 24), ratio, mode)
                actual = cached.pixmap(QSize(24, 24), ratio, mode)
                assert actual.devicePixelRatio() == ratio
                assert actual.toImage() == expected.toImage()


def test_icon_wrapper_preserves_special_icons_and_existing_lookup_identity(qt_application):
    class FontIcon(fluent_icons.FluentFontIconBase):
        def __init__(self):
            # 本用例只验证字体图标不会被替换，无须加载外部字体资源。
            pass

    colored = FluentIcon.SETTING.colored("#123456", "#abcdef")
    font = FontIcon()
    qicon = QIcon()
    for source in (colored, font, qicon, "fixture.png", icon_loader.DEVICE_ICON):
        assert _cached(source) is source
    wrapped = _cached(FluentIcon.SETTING)
    assert _cached(wrapped) is wrapped
    assert icon_loader.get_fluent_icon("speaker-low.svg") is FluentIcon.MUTE
    assert icon_loader.get_fluent_icon("keyboard.svg") is FluentIcon.COMMAND_PROMPT


def test_renderer_cache_evicts_old_colors_instead_of_growing_without_bound(svg_calls):
    arrow = _cached(FluentIcon.ARROW_DOWN)
    for color in range(160):
        _render(arrow, fill=f"#{color:06x}")
    live = [ref() for ref in svg_calls[2] if ref() is not None and isValid(ref())]
    assert len(live) <= 128
    before = len(svg_calls[0])
    _render(arrow, fill="#000000")
    assert len(svg_calls[0]) == before + 1, "容量溢出后最早使用的颜色应重新解析"


def test_worker_render_does_not_share_gui_thread_renderer(svg_calls):
    icon = _cached(FluentIcon.SETTING)
    expected = _render(icon)
    rendered, errors = [], []

    def worker():
        try:
            rendered.append(_render(icon))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not errors
    assert rendered == [expected]
    _render(icon)
    assert len(svg_calls[0]) == 2
    assert svg_calls[0][0] != svg_calls[0][1]


def test_explicit_cache_clear_releases_renderers_and_later_paint_rebuilds(svg_calls):
    cache = sys.modules.get("gui.styles.cached_icon")
    assert cache is not None, "静态 SVG 缓存尚未接入"
    icon = _cached(FluentIcon.SETTING)
    _render(icon)
    references = list(svg_calls[2])
    cache.clear_icon_caches()
    assert all(ref() is None or not isValid(ref()) for ref in references)
    _render(icon)
    assert len(svg_calls[0]) == 2


@pytest.mark.parametrize("button_type", [PushButton, PrimaryPushButton, ToolButton])
@pytest.mark.parametrize("explicit_color", [False, True])
def test_configured_buttons_keep_theme_color_disabled_and_pressed_pixels(
    qt_application, button_type, explicit_color,
):
    source = FluentIcon.SETTING
    if explicit_color:
        source = source.colored("#234567", "#abcdef")
    button = button_type()
    button.setIcon(source)
    configure_button(button, text="操作", tooltip="操作")
    prepared = button._icon
    button.resize(140, 42)
    try:
        for theme in ("Light", "Dark", "Light"):
            BaseStyles.switch_theme(theme)
            for enabled, pressed in ((True, False), (True, True), (False, False)):
                button.setEnabled(enabled)
                button.isPressed = pressed
                button.setIcon(source)
                expected = button.grab().toImage()
                button.setIcon(prepared)
                assert button.grab().toImage() == expected
        if explicit_color:
            assert prepared is source
    finally:
        button.close()
        button.deleteLater()


@pytest.mark.parametrize("button_type", [PushButton, ToolButton])
def test_configured_buttons_reuse_renderer_in_actual_paints(svg_calls, button_type):
    button = button_type()
    button.setIcon(FluentIcon.SETTING)
    configure_button(button, text="操作", tooltip="执行操作")
    button.resize(140, 42)
    try:
        sys.modules["gui.styles.cached_icon"].clear_icon_caches()
        svg_calls[0].clear()
        for _ in range(5):
            button.grab()
        assert len(svg_calls[0]) == 1
        prepared = button._icon
        configure_button(button, text="操作", tooltip="执行操作")
        assert button._icon is prepared
    finally:
        button.close()
        button.deleteLater()


def test_native_qt_button_keeps_its_original_icon(qt_application):
    button = QPushButton()
    icon = FluentIcon.SETTING.icon(Theme.LIGHT)
    button.setIcon(icon)
    configure_button(button, text="操作", tooltip="执行操作")
    assert button.icon().cacheKey() == icon.cacheKey()
    assert not hasattr(button, "_icon")
    button.deleteLater()


def test_action_card_reuses_renderer_in_actual_icon_paints(svg_calls):
    from gui.pages.fluent_pages import ActionCard

    card = ActionCard(FluentIcon.SETTING, "设置", "调整界面", lambda: None)
    icon = card.findChild(IconWidget)
    assert icon is not None
    try:
        for _ in range(5):
            icon.grab()
        assert len(svg_calls[0]) == 1
    finally:
        card.close()
        card.deleteLater()


def test_settings_cards_only_parse_icons_on_cold_paint(svg_calls, make_page):
    page = make_page()
    labels = [presentation.card.iconLabel for presentation in page._card_presentations]
    labels += [page.adb_client_card.card.iconLabel, page.adb_check_card.card.iconLabel]
    cache = sys.modules["gui.styles.cached_icon"]
    for theme in ("Light", "Dark", "Light"):
        BaseStyles.switch_theme(theme)
        cache.clear_icon_caches()
        svg_calls[0].clear()
        cold_images = [label.grab().toImage() for label in labels]
        cold_count = len(svg_calls[0])
        assert 0 < cold_count <= len(labels)
        warm_images = [label.grab().toImage() for label in labels]
        assert warm_images == cold_images
        assert len(svg_calls[0]) == cold_count, "设置卡每次重绘仍重复解析静态图标"

