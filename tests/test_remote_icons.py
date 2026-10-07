"""验证远程动作图标使用准确资源，并保留 Fluent 的主题与缩放绘制。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from qfluentwidgets import FluentIcon

from gui.styles import BaseStyles
from gui.styles.icon_loader import get_fluent_icon, get_themed_icon

pytestmark = pytest.mark.ui

_REMOTE_ASSETS = (
    ("remote-volume-down.svg", "speaker-low.svg"),
    ("remote-volume-up.svg", "speaker-high.svg"),
    ("remote-media-prev.svg", "skip-back.svg"),
    ("remote-media-next.svg", "skip-forward.svg"),
    ("remote-play-pause.svg", "play-pause.svg"),
    ("remote-enter.svg", "arrow-elbow-down-left.svg"),
    ("remote-backspace.svg", "backspace.svg"),
    ("remote-notification-expand.svg", "arrow-line-down.svg"),
    ("remote-notification-collapse.svg", "arrow-line-up.svg"),
    ("remote-portrait.svg", "device-mobile.svg"),
    ("remote-landscape.svg", "rectangle.svg"),
    ("remote-recents.svg", "cards.svg"),
)


def _visible_pixels(image):
    return [
        color for y in range(image.height()) for x in range(image.width())
        if (color := image.pixelColor(x, y)).alpha() > 0
    ]


@pytest.mark.parametrize(("alias", "filename"), _REMOTE_ASSETS)
def test_remote_icon_uses_existing_asset_and_renders_in_live_themes(
    qt_application, alias, filename,
):
    icon = get_fluent_icon(alias)
    expected = Path(__file__).parents[1] / "resources" / "icons" / filename
    assert Path(icon.path()).resolve() == expected.resolve()
    assert expected.is_file()
    themed = get_themed_icon(alias)
    for theme, channel in (("Light", 0), ("Dark", 255)):
        BaseStyles.switch_theme(theme)
        for size in (16, 32):
            for ratio in (1.0, 2.0):
                pixmap = themed.pixmap(QSize(size, size), ratio)
                assert pixmap.devicePixelRatio() == ratio
                assert pixmap.width() == pixmap.height() == round(size * ratio)
                pixels = _visible_pixels(pixmap.toImage())
                assert pixels
                assert max(pixel.alpha() for pixel in pixels) > 128
                assert all(pixel.red() == pixel.green() == pixel.blue() == channel
                           for pixel in pixels)


def test_remote_icon_keeps_explicit_tint_and_disabled_opacity(qt_application):
    icon = get_fluent_icon("remote-backspace.svg")
    tint = QColor("#0078d4")
    colored = _visible_pixels(icon.icon(color=tint).pixmap(32, 32).toImage())
    assert any(pixel == tint for pixel in colored)
    themed = icon.qicon()
    normal = _visible_pixels(themed.pixmap(32, 32, QIcon.Mode.Normal).toImage())
    disabled = _visible_pixels(themed.pixmap(32, 32, QIcon.Mode.Disabled).toImage())
    assert disabled
    normal_alpha = sum(pixel.alpha() for pixel in normal)
    disabled_alpha = sum(pixel.alpha() for pixel in disabled)
    assert 0.45 < disabled_alpha / normal_alpha < 0.55


def test_remote_aliases_do_not_replace_shared_compatibility_icons():
    assert get_fluent_icon("speaker-low.svg") is FluentIcon.MUTE
    assert get_fluent_icon("skip-back.svg") is FluentIcon.SKIP_BACK
    assert get_fluent_icon("skip-forward.svg") is FluentIcon.SKIP_FORWARD
    assert get_fluent_icon("backspace.svg") is FluentIcon.REMOVE
    assert get_fluent_icon("keyboard.svg") is FluentIcon.COMMAND_PROMPT
