import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, QSize, Signal
from PySide6.QtWidgets import QDialog
from shiboken6 import delete, isValid

from gui.dialogs.lifecycle import (
    alive_forwarding_callback,
    alive_signal_emitter,
    fit_secondary_window_to_owner_screen,
)


class _LifecycleProbe(QObject):
    message = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, *args):
        self.calls.append(args)


def test_secondary_window_is_clamped_to_owner_screen(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(980, 700)
    dialog.resize(1100, 800)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(100, 50, 800, 600))
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(200, 100, 500, 400),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(776, 576)
    assert dialog.size() == QSize(776, 576)
    assert 100 <= dialog.x() <= 124
    assert 50 <= dialog.y() <= 74
    dialog.close()


def test_secondary_window_keeps_smaller_declared_minimum(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(520, 420)
    dialog.resize(760, 620)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1200, 800))
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(100, 100, 860, 500),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(520, 420)
    assert dialog.size() == QSize(760, 620)
    dialog.close()


def test_secondary_window_restores_original_geometry_after_small_screen_clamp(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(980, 700)
    dialog.resize(1100, 800)
    screen_geometry = {"value": QRect(100, 50, 800, 600)}
    screen = SimpleNamespace(availableGeometry=lambda: screen_geometry["value"])
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(200, 100, 500, 400),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)
    assert dialog.minimumSize() == QSize(776, 576)
    assert dialog.size() == QSize(776, 576)

    screen_geometry["value"] = QRect(0, 0, 1600, 1000)
    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(980, 700)
    assert dialog.size() == QSize(1100, 800)
    dialog.close()


def test_late_callbacks_ignore_deleted_qobject(qt_application):
    probe = _LifecycleProbe()
    probe.message.connect(probe.record)
    forward = alive_forwarding_callback(probe, "record")
    emit = alive_signal_emitter(probe, "message", "RAW")

    forward("direct")
    emit("signal")

    assert probe.calls == [("direct",), ("RAW", "signal")]

    delete(probe)
    forward("late-direct")
    emit("late-signal")


def test_remote_form_disconnects_global_style_signals_with_its_visual_root(
    monkeypatch, qt_application,
):
    """保留 Python 控制器引用，销毁视图后仍不能收到跨窗口的主题与字体回调。"""

    from core.settings_manager import DEFAULTS, AppSettings
    from gui.panels.remote_panel import RemotePanel
    from gui.panels.side_panel import SidePanel
    from gui.styles import BaseStyles
    from models.device_store import DeviceStore

    values = dict(DEFAULTS)
    settings = SimpleNamespace(get=values.get, set=lambda key, value: values.update({key: value}))
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    monkeypatch.setattr(DeviceStore, "_devices", {})
    monkeypatch.setattr(DeviceStore, "load", classmethod(lambda cls: None))
    theme_calls = []
    callback_errors = []
    original_theme_callback = RemotePanel._on_theme_changed_remote

    def record_theme_callback(panel, name):
        theme_calls.append(name)
        original_theme_callback(panel, name)

    monkeypatch.setattr(RemotePanel, "_on_theme_changed_remote", record_theme_callback)
    monkeypatch.setattr(sys, "excepthook", lambda *error: callback_errors.append(error))
    original_windows = set(qt_application.topLevelWidgets())
    side_panel = SidePanel()
    remote = side_panel._ensure_tab_loaded(2)
    form = remote._form_controller
    try:
        theme_calls.clear()
        BaseStyles.theme_changed.emit(BaseStyles.current_theme())
        BaseStyles.fonts_changed.emit(BaseStyles.current_font_config())
        assert len(theme_calls) == 1
        assert callback_errors == []

        side_panel.shutdown()
        assert remote._remote_input_shutdown.wait(1.0)
        visual_roots = set(qt_application.topLevelWidgets()) - original_windows - {remote}
        for widget in visual_roots:
            if isValid(widget):
                delete(widget)

        # Python 强引用仍在，验证 Qt 连接归属，而不是依赖垃圾回收碰巧清掉回调。
        assert remote._form_controller is form
        theme_calls.clear()
        BaseStyles.theme_changed.emit(BaseStyles.current_theme())
        BaseStyles.fonts_changed.emit(BaseStyles.current_font_config())
        qt_application.processEvents()
        assert theme_calls == []
        assert callback_errors == []
    finally:
        if isValid(side_panel):
            side_panel.shutdown()
        for widget in set(qt_application.topLevelWidgets()) - original_windows:
            if isValid(widget):
                delete(widget)


def test_side_panel_disposes_hidden_controllers_before_late_style_changes(
    monkeypatch, qt_application,
):
    """协调器销毁后，强引用保留的控制器也不能继续读取已释放的设备视图。"""
    from core.settings_manager import DEFAULTS, AppSettings
    from gui.panels.side_panel import SidePanel
    from gui.styles import BaseStyles
    from models.device_store import DeviceStore

    values = dict(DEFAULTS)
    settings = SimpleNamespace(get=values.get, set=lambda key, value: values.update({key: value}))
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    monkeypatch.setattr(DeviceStore, "_devices", {})
    monkeypatch.setattr(DeviceStore, "load", classmethod(lambda cls: None))
    original_windows = set(qt_application.topLevelWidgets())
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    panel = SidePanel()
    apps = panel._ensure_tab_loaded(0)
    system = panel._ensure_tab_loaded(1)
    devices = panel._devices_tab
    try:
        BaseStyles.theme_changed.emit(BaseStyles.current_theme())
        assert errors == []
        panel.shutdown()
        delete(panel.device_widget)
        delete(panel)
        BaseStyles.theme_changed.emit(BaseStyles.current_theme())
        BaseStyles.fonts_changed.emit(BaseStyles.current_font_config())
        qt_application.processEvents()
        assert errors == []
        assert not any(isValid(controller) for controller in (apps, system, devices))
    finally:
        for widget in set(qt_application.topLevelWidgets()) - original_windows:
            if isValid(widget):
                delete(widget)
