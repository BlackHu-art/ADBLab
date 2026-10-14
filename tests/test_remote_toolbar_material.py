"""独立侧栏原生材质只消费宿主状态，失败后保持可读实色底板。"""

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget

pytestmark = pytest.mark.ui


def test_toolbar_mica_follows_host_and_theme_without_recreating_controls(
    qt_application, monkeypatch,
):
    from gui.styles import BaseStyles
    from gui.widgets import remote_toolbar_material as material
    from gui.widgets.remote_toolbar import RemoteToolbar

    class Host(QWidget):
        enabled = True

        def isMicaEffectEnabled(self):
            return self.enabled

    monkeypatch.setattr(material, "_native_mica_available", lambda: True)
    calls = []
    monkeypatch.setattr(material, "_apply_native_mica", lambda hwnd, enabled, dark: (
        calls.append((hwnd, enabled, dark)), enabled,
    )[1])
    host = Host()
    toolbar = RemoteToolbar(host)
    try:
        toolbar.set_available(True)
        toolbar.show()
        toolbar._toggle_popup()
        qt_application.processEvents()
        buttons = tuple(toolbar._commands.values())
        assert toolbar.isMicaEffectEnabled()
        assert toolbar.popup_window.isMicaEffectEnabled()
        assert not toolbar._popup_content.autoFillBackground()
        assert not toolbar._popup_scroll.viewport().autoFillBackground()
        assert "background: transparent" in toolbar.styleSheet()
        calls.clear()
        for _ in range(8):
            qt_application.sendEvent(host, QEvent(QEvent.Type.UpdateRequest))
        assert calls == []
        BaseStyles.switch_theme("Dark")
        assert calls[-1][2] is True
        host.enabled = False
        qt_application.sendEvent(host, QEvent(QEvent.Type.UpdateRequest))
        assert not toolbar.isMicaEffectEnabled()
        assert not toolbar.popup_window.isMicaEffectEnabled()
        assert BaseStyles.color("TOOLBAR_BG") in toolbar.styleSheet()
        assert tuple(toolbar._commands.values()) == buttons
        assert toolbar.popup_window.isVisible()
        host.enabled = True
        qt_application.sendEvent(host, QEvent(QEvent.Type.UpdateRequest))
        assert toolbar.isMicaEffectEnabled()
        assert toolbar.popup_window.isMicaEffectEnabled()
    finally:
        toolbar.dispose()
        host.close()


@pytest.mark.parametrize("failure", ["frame", "dark", "corners", "backdrop", None])
def test_native_mica_failure_and_disable_revoke_backdrop_and_frame(monkeypatch, failure):
    from gui.widgets import remote_toolbar_material as material

    calls = []

    def frame(hwnd, enabled):
        calls.append(("frame", enabled))
        return not (enabled and failure == "frame")

    def attribute(hwnd, key, value):
        calls.append((key, value))
        return not ((key == 20 and failure == "dark") or (key == 33 and failure == "corners"))

    def backdrop(hwnd, enabled):
        calls.append(("backdrop", enabled))
        return not (enabled and failure == "backdrop")

    monkeypatch.setattr(material, "_extend_frame", frame)
    monkeypatch.setattr(material, "set_dwm_attribute", attribute)
    monkeypatch.setattr(material, "sync_mica_backdrop", backdrop)
    assert material._apply_native_mica(42, True, True) is (failure is None)
    if failure is not None:
        assert calls[-3:] == [("backdrop", False), ("frame", False), (33, 1)]
    calls.clear()
    assert not material._apply_native_mica(42, False, True)
    assert calls == [("backdrop", False), ("frame", False), (33, 1)]


def test_disposed_material_observer_does_not_update_retired_windows(qt_application, monkeypatch):
    from gui.styles import BaseStyles
    from gui.widgets import remote_toolbar_material as material
    from gui.widgets.remote_toolbar import RemoteToolbar

    host = QWidget()
    monkeypatch.setattr(host, "isMicaEffectEnabled", lambda: True, raising=False)
    monkeypatch.setattr(material, "_native_mica_available", lambda: True)
    attempts = []
    monkeypatch.setattr(material, "_apply_native_mica", lambda *args: (
        attempts.append(args), True,
    )[1])
    toolbar = RemoteToolbar(host)
    try:
        toolbar.show()
        toolbar.dispose()
        attempts.clear()
        qt_application.sendEvent(host, QEvent(QEvent.Type.UpdateRequest))
        BaseStyles.theme_changed.emit("Dark")
        assert attempts == []
    finally:
        toolbar.dispose()
        host.close()


@pytest.mark.parametrize("supported", [False, True])
def test_unsupported_or_failed_mica_keeps_opaque_theme_surface(
    qt_application, monkeypatch, supported,
):
    from gui.styles import BaseStyles
    from gui.widgets import remote_toolbar_material as material
    from gui.widgets.remote_toolbar import RemoteToolbar

    host = QWidget()
    monkeypatch.setattr(host, "isMicaEffectEnabled", lambda: True, raising=False)
    monkeypatch.setattr(material, "_native_mica_available", lambda: supported)
    attempts = []
    monkeypatch.setattr(material, "_apply_native_mica", lambda *args: (
        attempts.append(args), False,
    )[1])
    toolbar = RemoteToolbar(host)
    try:
        toolbar.show()
        qt_application.processEvents()
        assert not toolbar.isMicaEffectEnabled()
        assert BaseStyles.color("TOOLBAR_BG") in toolbar.styleSheet()
        assert bool(attempts) is supported
    finally:
        toolbar.dispose()
        host.close()
