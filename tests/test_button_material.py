"""验证按钮禁用底板跟随真实宿主，样式刷新保留页面字体。"""

import pytest
from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton, SettingCard

from gui.features.about import AboutPanel
from gui.styles import BaseStyles
from gui.styles.fluent import configure_button, refresh_fluent_widget_style

pytestmark = pytest.mark.ui


class MaterialHost(QWidget):
    def __init__(self, mica=False):
        super().__init__()
        self.mica = mica
        self.backdrop = QColor("#245884")

    def isMicaEffectEnabled(self):
        return self.mica

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.backdrop)


def samples(app, host, button):
    colors = []
    for value in ("#245884", "#99522f"):
        host.backdrop = QColor(value)
        host.update()
        app.processEvents()
        point = button.mapTo(host, QPoint(button.width() - 25, button.height() // 2))
        image = host.grab().toImage()
        scale = image.devicePixelRatio()
        colors.append(image.pixelColor(round(point.x() * scale), round(point.y() * scale)))
    return colors


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("danger", [False, True])
def test_disabled_button_material_tracks_host_and_restores_plain_mode(
    qt_application, theme, danger,
):
    BaseStyles.switch_theme(theme)
    host = MaterialHost()
    layout = QHBoxLayout(host)
    button = configure_button(PrimaryPushButton(), text="执行", tooltip="执行操作", danger=danger)
    button.setFixedSize(240, 44)
    button.setEnabled(False)
    layout.addWidget(button)
    host.show()
    try:
        original = samples(qt_application, host, button)
        assert original[0] == original[1]
        host.mica = True
        colors = samples(qt_application, host, button)
        assert colors[0] != colors[1]
        host.mica = False
        assert samples(qt_application, host, button) == original
        host.mica = True
        assert samples(qt_application, host, button)[0] != original[0]
        plain = MaterialHost()
        plain_layout = QHBoxLayout(plain)
        plain_layout.addWidget(button)
        plain.show()
        try:
            assert samples(qt_application, plain, button) == original
        finally:
            plain.close()
            plain.deleteLater()
    finally:
        host.close()
        host.deleteLater()


def test_about_button_refresh_preserves_rendered_font(qt_application, monkeypatch):
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    card = SettingCard(FluentIcon.INFO, "关于")
    button = configure_button(PrimaryPushButton(card), text="下载", tooltip="打开下载")
    card.hBoxLayout.addWidget(button)
    AboutPanel._style_action_button(button)
    card.show()
    qt_application.processEvents()
    expected = button.font()
    try:
        refresh_fluent_widget_style(button)
        qt_application.processEvents()
        assert button.font() == expected
    finally:
        card.close()
        card.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_mica_disabled_primary_icon_matches_native_neutral_icon(qt_application, theme):
    BaseStyles.switch_theme(theme)
    host = MaterialHost(True)
    button = configure_button(PrimaryPushButton(host), text="执行", tooltip="执行操作")
    reference = PushButton(host)
    primary_reference = PrimaryPushButton(host)

    def icon_image(control):
        image = QImage(24, 24, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#808080"))
        painter = QPainter(image)
        painter.setOpacity(0.3628)
        control._drawIcon(FluentIcon.ADD, painter, QRectF(2, 2, 20, 20))
        painter.end()
        return image

    for control in (button, reference, primary_reference):
        control.setEnabled(False)
    try:
        assert icon_image(button) == icon_image(reference)
        host.mica = False
        assert icon_image(button) == icon_image(primary_reference)
        button.setEnabled(True)
        primary_reference.setEnabled(True)
        host.mica = True
        assert icon_image(button) == icon_image(primary_reference)
    finally:
        host.deleteLater()
