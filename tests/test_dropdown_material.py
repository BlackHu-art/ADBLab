"""验证项目下拉保留原生状态底板，并从真实父层接收材质。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, EditableComboBox, FluentWindow

from gui.styles import BaseStyles
from gui.styles.fluent import configure_fluent_control
from gui.widgets.preset_spin_box import StrictIntComboBox
from tests.test_navigation_rendering import theme_probe_frame as theme_probe_frame
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui

_BACKDROPS = (QColor("#245884"), QColor("#99522f"))


class _PaintedHost(QWidget):
    def __init__(self):
        super().__init__()
        self.backdrop = _BACKDROPS[0]
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.backdrop)


def _make_field(kind, parent):
    if kind == "strict":
        field = StrictIntComboBox(1, 100, 30, presets=(10, 30, 60), parent=parent)
    else:
        field = (ComboBox if kind == "combo" else EditableComboBox)(parent)
        field.addItems(["10", "30", "60"])
        field.setCurrentIndex(1)
    for index in range(3):
        field.setItemData(index, f"option-{index}")
    return field


def _pixel(owner, widget, point=None):
    # 在完整父层合成图上取样，避免单独 grab 子控件丢失祖先底色。
    point = point or QPoint(widget.width() * 2 // 3, widget.height() // 2)
    point = widget.mapTo(owner, point)
    image = owner.grab().toImage()
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


def _distance(first, second):
    return max(abs(a - b) for a, b in zip(first.getRgb()[:3], second.getRgb()[:3]))


def _show_state(app, owner, field, state):
    field.setEnabled(True)
    owner.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.mouseMove(owner, QPoint(owner.width() - 2, owner.height() - 2))
    if state == "hover":
        QTest.mouseMove(field, QPoint(field.width() // 2, field.height() // 2))
        wait_until(app, field.underMouse)
    elif state == "focus":
        field.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(app, field.hasFocus)
    elif state == "disabled":
        field.setEnabled(False)
    app.processEvents()
    # Windows 鼠标离开事件可能晚于 setFocus；只比较相同 hover 状态的实绘结果。
    wait_until(app, lambda: field.underMouse() == (state == "hover"))


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("kind", ["combo", "editable", "strict"])
def test_project_dropdown_preserves_reference_background_in_each_state(
    qt_application, theme, kind,
):
    """项目字体/焦点配置不得把原生半透明底板改成实色或全透明。"""
    BaseStyles.switch_theme(theme)
    owner = _PaintedHost()
    layout = QVBoxLayout(owner)
    reference = _make_field(kind, owner)
    configured = configure_fluent_control(_make_field(kind, owner))
    for field in (reference, configured):
        field.setFixedSize(300, 44)
        layout.addWidget(field)
    owner.resize(340, 160)
    owner.show()
    original = (configured.currentIndex(), configured.currentText(), configured.currentData())
    index_changed = QSignalSpy(configured.currentIndexChanged)
    text_changed = QSignalSpy(configured.currentTextChanged)
    try:
        for state in ("normal", "hover", "focus", "disabled"):
            colors = []
            for field in (reference, configured):
                _show_state(qt_application, owner, field, state)
                samples = []
                for backdrop in _BACKDROPS:
                    owner.backdrop = backdrop
                    owner.update()
                    samples.append(_pixel(owner, field))
                colors.append(samples)
            for native, project in zip(*colors):
                assert _distance(native, project) <= 2, (kind, theme, state, colors)
            if state == "focus" and theme == "Light" and kind != "combo":
                assert colors[1] == [QColor("white"), QColor("white")]
            else:
                # 两种底色都应可见，同时保留控件自身的状态遮罩。
                assert _distance(*colors[1]) >= 20, (kind, theme, state, colors[1])
                assert all(
                    _distance(actual, backdrop) >= 3
                    for actual, backdrop in zip(colors[1], _BACKDROPS)
                ), (kind, theme, state, colors[1])
        assert (
            configured.currentIndex(), configured.currentText(), configured.currentData()
        ) == original
        assert index_changed.count() == text_changed.count() == 0
        if kind == "strict":
            assert configured.value() == 30
    finally:
        owner.close()
        owner.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("kind", ["combo", "editable", "strict"])
def test_dropdown_popup_keeps_readable_surface_and_enabled_selection(
    qt_application, theme, kind,
):
    """独立 popup 保留实色底板，禁用项不能选中，有效项仍只提交一次。"""
    BaseStyles.switch_theme(theme)
    owner = _PaintedHost()
    field = configure_fluent_control(_make_field(kind, owner))
    field.setItemEnabled(0, False)
    field.setFixedWidth(300)
    QVBoxLayout(owner).addWidget(field)
    owner.resize(340, 100)
    owner.show()
    changed = QSignalSpy(field.currentIndexChanged)
    activated = QSignalSpy(field.activated)
    try:
        button = field if kind == "combo" else field.dropButton
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        wait_until(qt_application, lambda: field.dropMenu is not None)
        menu = field.dropMenu
        wait_until(
            qt_application,
            lambda: menu.isVisible()
            and menu.aniManager.ani.state() == QAbstractAnimation.State.Stopped,
        )
        QTest.mouseMove(owner, QPoint(2, 2))
        expected = QColor("#f9f9f9" if theme == "Light" else "#2b2b2b")
        # 列表两侧留白不包含选中/hover 高亮；透明 viewport 会在此暴露出来。
        assert _pixel(menu, menu.view.viewport(), QPoint(1, 8)) == expected
        assert menu.view.item(1).isSelected()
        disabled = menu.view.item(0)
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(disabled).center(),
        )
        assert field.currentIndex() == 1
        assert changed.count() == activated.count() == 0
        assert menu.isVisible()

        selected = menu.view.item(2)
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(selected).center(),
        )
        assert field.currentText() == "60"
        assert field.currentData() == "option-2"
        assert changed.count() == activated.count() == 1
        if kind == "strict":
            assert field.value() == 60
    finally:
        if field.dropMenu is not None:
            field.dropMenu.close()
        owner.close()
        owner.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_settings_dropdown_inherits_shell_material_without_selection_changes(
    qt_application, monkeypatch, theme_probe_frame, theme,
):
    """真实设置页的父层透色，切换 Mica 不重建下拉或提交配置值。"""
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    frame = theme_probe_frame(theme, False)

    def native_mica(window, enabled):
        window._isMicaEnabled = enabled
        window.setBackgroundColor(window._normalBackgroundColor())

    # 仅替代系统 DWM 开关，仍走生产 MainFrame 的材质同步和实际页面。
    monkeypatch.setattr(FluentWindow, "setMicaEffectEnabled", native_mica)
    frame._on_nav_requested("settings")
    wait_until(
        qt_application,
        lambda: frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped,
    )
    field = frame._settings_page.log_lines_card.combo_box
    frame._settings_page.ensureWidgetVisible(field)
    wait_until(qt_application, lambda: field.isVisibleTo(frame))
    QTest.mouseMove(frame.titleBar, QPoint(5, 5))
    field.clearFocus()
    original = (field.currentIndex(), field.currentText(), field.currentData())
    changed = QSignalSpy(field.currentIndexChanged)
    text_changed = QSignalSpy(field.currentTextChanged)
    opaque = _pixel(frame, field, QPoint(field.width() // 2, 5))

    colors = []
    for backdrop in _BACKDROPS:
        frame.setMicaEffectEnabled(True)
        frame.backgroundColorAni.stop()
        frame.setBackgroundColor(backdrop)
        colors.append(_pixel(frame, field, QPoint(field.width() // 2, 5)))
    assert _distance(*colors) >= 4, (theme, colors)
    assert colors[0] != opaque
    frame.setMicaEffectEnabled(False)
    frame.backgroundColorAni.stop()
    assert _distance(_pixel(frame, field, QPoint(field.width() // 2, 5)), opaque) <= 2
    assert (field.currentIndex(), field.currentText(), field.currentData()) == original
    assert changed.count() == text_changed.count() == 0
