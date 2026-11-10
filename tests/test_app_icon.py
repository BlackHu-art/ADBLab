"""应用与主窗口图标应保留高分辨率资源，兼容普通和高 DPI 请求。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from utils.resource_path import resource_path


@pytest.mark.ui
@pytest.mark.parametrize("logical_size,dpr", [
    (16, 1.0), (32, 2.0), (48, 1.5), (128, 2.0),
    (256, 2.0), (512, 2.0), (1024, 1.0),
])
def test_application_icon_renders_requested_pixels(qt_application, logical_size, dpr):
    from utils.app_icon import load_app_icon

    pixmap = load_app_icon().pixmap(QSize(logical_size, logical_size), dpr)

    assert not pixmap.isNull()
    physical_size = int(logical_size * dpr)
    assert pixmap.size() == QSize(physical_size, physical_size)
    assert pixmap.devicePixelRatio() == pytest.approx(dpr)


@pytest.mark.ui
@pytest.mark.parametrize("source", ["missing", "corrupt"])
def test_application_icon_falls_back_when_png_is_unavailable(
    qt_application, monkeypatch, tmp_path, source,
):
    from utils import app_icon

    png = tmp_path / "app-icon.png"
    if source == "corrupt":
        png.write_bytes(b"not a valid image")
    fallback = resource_path("icon.ico")
    monkeypatch.setattr(
        app_icon, "resource_path",
        lambda path: str(png) if path == "resources/app-icon.png" else fallback,
    )

    icon = app_icon.load_app_icon()

    assert not icon.isNull()
    assert icon.pixmap(QSize(64, 64)).toImage() == QIcon(fallback).pixmap(QSize(64, 64)).toImage()


@pytest.mark.ui
def test_gui_entry_supplies_large_application_icon(qt_application, monkeypatch):
    import main
    from core import settings_manager

    class IconAssigned(Exception):
        pass

    class Application:
        def __init__(self, _argv):
            pass

        def setWindowIcon(self, icon):  # noqa: N802
            icons.append(icon)
            raise IconAssigned

    icons = []
    monkeypatch.setattr(main, "configure_gui_platform", lambda _argv: False)
    monkeypatch.setattr(main, "_configure_console_logging", lambda _settings: None)
    monkeypatch.setattr(main, "_configure_gui_scaling", lambda _value: None)
    monkeypatch.setattr(settings_manager.AppSettings, "instance", lambda **_kwargs: {})
    monkeypatch.setattr(settings_manager, "_error_sink", None)
    monkeypatch.setattr("utils.adb_resolver.set_client_preference", lambda _value: None)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", Application)

    with pytest.raises(IconAssigned):
        main._run_gui_session(SimpleNamespace(record=lambda *_args, **_kwargs: None))

    assert icons[0].pixmap(QSize(512, 512)).size() == QSize(512, 512)


@pytest.mark.ui
def test_mainframe_supplies_large_window_icon(qt_application):
    from gui.main_frame import MainFrame

    class IconAssigned(Exception):
        pass

    class WindowIconProbe(QWidget):
        def setWindowIcon(self, icon):  # noqa: N802
            super().setWindowIcon(icon)
            raise IconAssigned

    # 只执行真实窗口设置入口直到图标赋值，避免启动无关页面及设备服务。
    window = WindowIconProbe()
    with pytest.raises(IconAssigned):
        MainFrame._setup_window(window)

    assert window.windowIcon().pixmap(QSize(512, 512)).size() == QSize(512, 512)
