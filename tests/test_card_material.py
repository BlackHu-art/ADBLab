"""卡片在实际云母宿主、重挂与主题变化时保持统一材质和交互。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import SettingCard

from gui.styles import BaseStyles
from gui.widgets.adb_client_card import AdbEnvironmentSettingCard
from gui.widgets.material_card import MaterialCard
from tests.test_navigation_rendering import (
    _expected_content_color,
)
from tests.test_navigation_rendering import (
    theme_probe_frame as theme_probe_frame,
)
from tests.ui_geometry_helpers import wait_until

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("isolated_settings_client_detection")]


def _over(background, alpha):
    image = QImage(1, 1, QImage.Format.Format_RGB32)
    image.fill(background)
    painter = QPainter(image)
    painter.fillRect(image.rect(), QColor(255, 255, 255, alpha))
    painter.end()
    return image.pixelColor(0, 0)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_settings_and_about_cards_follow_actual_host_material(
    qt_application, theme_probe_frame, theme,
):
    """普通卡、关于卡及折叠标题统一低覆盖，关闭云母后恢复原生填充。"""
    frame = theme_probe_frame(theme, True, width=1000)
    frame._on_nav_requested("settings")
    wait_until(qt_application, lambda: (
        frame._page_transition.animation.state() == QAbstractAnimation.State.Stopped
    ))
    cards = frame._settings_page.findChildren(SettingCard)
    assert len(cards) >= 20
    QTest.mouseMove(frame, QPoint(2, 2))
    for mica in (True, False, True):
        frame.setMicaEffectEnabled(mica)
        qt_application.processEvents()
        background = _expected_content_color(frame)
        alpha = 13 if theme == "Dark" else (64 if mica else 170)
        expected = _over(background, alpha)
        mismatches = []
        for card in cards:
            image = QImage(card.size(), QImage.Format.Format_RGB32)
            image.fill(background)
            card.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
            scale = image.devicePixelRatio()
            actual = image.pixelColor(round(20 * scale), round((card.height() - 8) * scale))
            if actual != expected:
                mismatches.append((card.titleLabel.text(), actual.name(), expected.name()))
        assert not mismatches, (theme, mica, mismatches)


@pytest.mark.parametrize("section,feature", [
    ("devices", "files"), ("apps", "manager"), ("system", "logcat"), ("system", "performance"),
])
def test_no_device_cards_use_the_same_mica_surface(
    qt_application, theme_probe_frame, section, feature,
):
    """没有设备时的大卡片也透出宿主，保持入口与空态文本。"""
    frame = theme_probe_frame("Light", True, width=1000)
    frame._open_workspace_feature(section, feature)
    wait_until(qt_application, lambda: (
        frame._page_transition.animation.state() == QAbstractAnimation.State.Stopped
    ))
    pages = [page for page in frame.findChildren(QWidget, "workspaceFeatureNoDevice")
             if page.isVisibleTo(frame)]
    assert pages, (section, feature)
    for page in pages:
        card = page.card
        QTest.mouseMove(frame, QPoint(2, 2))
        qt_application.processEvents()
        assert card.backgroundColor == QColor(255, 255, 255, 64)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_expand_setting_body_matches_header_and_restores_native_background(
    qt_application, theme,
):
    """展开正文与标题只有一层卡片底色，材质往返不改变模式或展开状态。"""
    BaseStyles.switch_theme(theme)
    host = QWidget()
    active = [True]
    host.isMicaEffectEnabled = lambda: active[0]
    backdrop = QColor("#425970")
    palette = host.palette()
    palette.setColor(host.backgroundRole(), backdrop)
    host.setPalette(palette)
    host.setAutoFillBackground(True)
    group = AdbEnvironmentSettingCard(host)
    group.move(10, 10)
    group.resize(560, group.height())
    host.resize(600, 700)
    host.show()
    try:
        group.setExpand(True)
        wait_until(qt_application, lambda: (
            group.expandAni.state() == QAbstractAnimation.State.Stopped
        ))
        for mica in (True, False, True):
            active[0] = mica
            host.update()
            qt_application.processEvents()
            image = host.grab().toImage()
            scale = image.devicePixelRatio()
            point = group.view.mapTo(host, QPoint(3, 8))
            actual = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
            expected = _over(backdrop, 13 if theme == "Dark" else (64 if mica else 170))
            assert actual == expected, (theme, mica, actual.name(), expected.name())
            assert group.isExpand
            assert group._mode == "auto"
    finally:
        host.close()
        host.deleteLater()


def test_material_card_keeps_hover_on_theme_change_and_native_reparent(qt_application):
    BaseStyles.switch_theme("Light")
    mica = QWidget()
    mica.isMicaEffectEnabled = lambda: True
    plain = QWidget()
    mica.resize(240, 160)
    plain.resize(240, 160)
    card = MaterialCard(mica)
    card.setGeometry(10, 10, 200, 100)
    mica.show()
    try:
        qt_application.processEvents()
        # 先经过卡片外部，避免前例遗留相同鼠标坐标时离屏平台省略 Enter。
        QTest.mouseMove(mica, QPoint(230, 150))
        qt_application.processEvents()
        QTest.mouseMove(card, QPoint(50, 50))
        wait_until(qt_application, lambda: (
            card.isHover and card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
        ))
        assert card.backgroundColor == QColor(255, 255, 255, 40)
        BaseStyles.switch_theme("Dark")
        assert card.backgroundColor == QColor(255, 255, 255, 21)
        QTest.mouseMove(mica, QPoint(230, 150))
        card.setParent(plain)
        card.show()
        # 新宿主保持隐藏，模拟页面换宿主；避免离屏平台自动投递跨窗 Enter。
        QCoreApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
        qt_application.processEvents()
        BaseStyles.switch_theme("Light")
        wait_until(qt_application, lambda: (
            not card.isHover and card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
        ))
        assert card.backgroundColor == QColor(255, 255, 255, 170)
    finally:
        mica.close()
        plain.close()
        mica.deleteLater()
        plain.deleteLater()
