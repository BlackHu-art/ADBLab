"""卡片在实际云母宿主、重挂与主题变化时保持统一材质和交互。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentWindow, SettingCard

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
@pytest.mark.parametrize("material_support", ["native", "supported", "refused"])
def test_settings_and_about_cards_follow_actual_host_material(
    qt_application, monkeypatch, theme_probe_frame, theme, material_support,
):
    """材质按实际宿主状态绘制，支持、拒绝及真实平台均保持正确回退。"""
    if material_support != "native":
        # 仅替换平台能力边界，卡片绘制和材质观察器仍走实际实现。
        def set_native_mica(window, enabled):
            window._isMicaEnabled = bool(enabled and material_support == "supported")
            window.setBackgroundColor(window._normalBackgroundColor())

        monkeypatch.setattr(FluentWindow, "setMicaEffectEnabled", set_native_mica)
        monkeypatch.setattr(
            "gui.window_effects.sync_mica_backdrop", lambda *_: material_support == "supported",
        )
    frame = theme_probe_frame(theme, True, width=1000)
    frame._on_nav_requested("settings")
    wait_until(qt_application, lambda: (
        frame._page_transition.animation.state() == QAbstractAnimation.State.Stopped
    ))
    cards = frame._settings_page.findChildren(SettingCard)
    assert len(cards) >= 20
    QTest.mouseMove(frame, QPoint(2, 2))
    for requested in (True, False, True):
        frame.setMicaEffectEnabled(requested)
        wait_until(qt_application, lambda: (
            frame.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
        ))
        qt_application.processEvents()
        mica = frame.isMicaEffectEnabled()
        if material_support != "native":
            assert mica is (requested and material_support == "supported")
        background = _expected_content_color(frame)
        # 请求开启不代表平台已应用；macOS、旧 Windows 或 DWM 拒绝时使用原生填充。
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
        # 单卡渲染与用户实际看到的整窗合成必须一致，不能只验证离屏取样。
        visible_card = frame._settings_page.save_card
        assert visible_card.isVisibleTo(frame)
        point = visible_card.mapTo(frame, QPoint(20, visible_card.height() - 8))
        assert frame.rect().contains(point)
        image = frame.grab().toImage()
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(point.x() * scale), round(point.y() * scale)) == expected


@pytest.mark.parametrize("section,feature", [
    ("devices", "files"), ("apps", "manager"), ("system", "logcat"), ("system", "performance"),
])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_no_device_pages_leave_shared_surface_uncovered(
    qt_application, theme_probe_frame, section, feature, theme,
):
    """无候选和候选未选两类空态均不叠底板，主题与材质往返保持原设备入口。"""
    frame = theme_probe_frame(theme, True, width=1000)
    host = frame._workspace_feature_hosts[section]
    for candidates in ([], ["surface-demo-a", "surface-demo-b"]):
        frame._on_devices_updated(candidates)
        frame.left_panel.set_selected_devices([])
        assert frame._open_workspace_feature(section, feature)
        page = host.no_device_page
        wait_until(qt_application, lambda: (
            frame._page_transition.animation.state() == QAbstractAnimation.State.Stopped
        ))
        assert page.isVisibleTo(frame)
        assert host.stack.currentWidget() is page
        assert host.current_feature == feature
        assert page.title_label.text()
        assert page.message_label.text()
        assert page.choose_button.isVisibleTo(frame) is (not candidates)
        assert page.choose_button.focusPolicy() != Qt.FocusPolicy.NoFocus
        point = QPoint(16, 16)
        assert page.card.childAt(point) is None
        for mica in (False, True, False):
            frame.setMicaEffectEnabled(mica)
            wait_until(qt_application, lambda: (
                frame.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
            ))
            qt_application.processEvents()
            image = frame.grab().toImage()
            scale = image.devicePixelRatio()
            sample = page.card.mapTo(frame, point)
            actual = image.pixelColor(round(sample.x() * scale), round(sample.y() * scale))
            assert actual == _expected_content_color(frame), (theme, mica, section, feature)


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
        wait_until(qt_application, lambda: mica.windowHandle().isExposed())
        qt_application.processEvents()
        # 本例验证材质跟随交互态；用正常 Enter 事件避免 Cocoa 原生指针异步调度。
        point = QPoint(50, 50)
        QCoreApplication.sendEvent(card, QEnterEvent(
            QPointF(point), QPointF(card.mapTo(mica, point)),
            QPointF(card.mapToGlobal(point)),
        ))
        wait_until(qt_application, lambda: (
            card.isHover and card.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
        ))
        assert card.backgroundColor == QColor(255, 255, 255, 40)
        BaseStyles.switch_theme("Dark")
        assert card.backgroundColor == QColor(255, 255, 255, 21)
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
