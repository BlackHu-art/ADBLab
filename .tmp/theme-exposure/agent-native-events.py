import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core.settings_manager import AppSettings
from models.device_store import DeviceStore
from gui.styles import BaseStyles
from tests.test_main_window_layout import _MainFrameSettings, build_main_frame

app = QApplication([])
settings = _MainFrameSettings()
settings.values.update(theme='Dark', mica_enabled=True)
getter = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute
getter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
getter.restype = ctypes.c_long
sender = ctypes.WinDLL('user32').SendMessageW
sender.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
sender.restype = wintypes.LPARAM

def attribute(frame, key):
    value = ctypes.c_int(-99)
    code = getter(int(frame.winId()), key, ctypes.byref(value), ctypes.sizeof(value))
    return [code, value.value]

def record(frame, tag):
    print(json.dumps(dict(tag=tag, dark=attribute(frame,20), backdrop=attribute(frame,38),
        qt=app.styleHints().colorScheme().name, theme=BaseStyles.resolved_theme(),
        visible=frame.isVisible())), flush=True)

with patch.object(AppSettings, 'instance', classmethod(lambda cls: settings)), patch.object(DeviceStore,'get_basic_devices_info',lambda:[]), patch.object(DeviceStore,'get_full_devices_info',lambda devices:[]):
    BaseStyles.switch_theme('Dark')
    frame = build_main_frame(settings=settings)
    try:
        # 保持隐藏，不抓屏、不影响主任务用于桌面合成采样的窗口焦点。
        QTest.qWait(150)
        record(frame, 'hidden-start')
        for name, message, wp, lp in [
            ('WM_THEMECHANGED', 0x31A, 0, 0),
            ('WM_DWMCOLORIZATIONCOLORCHANGED', 0x320, 0xFF112233, 0),
            ('WM_DWMCOMPOSITIONCHANGED', 0x31E, 0, 0),
            ('WM_ACTIVATEAPP-false', 0x1C, 0, 0),
            ('WM_ACTIVATEAPP-true', 0x1C, 1, 0),
            ('WM_ACTIVATE-inactive', 0x6, 0, 0),
            ('WM_ACTIVATE-active', 0x6, 1, 0),
        ]:
            sender(int(frame.winId()), message, wp, lp)
            record(frame,name+'-sync')
            QTest.qWait(160)
            record(frame,name+'-deferred')
        for name in ('ImmersiveColorSet','WindowsThemeElement'):
            data=ctypes.create_unicode_buffer(name)
            sender(int(frame.winId()),0x1A,0,ctypes.cast(data,ctypes.c_void_p).value)
            record(frame,'WM_SETTINGCHANGE-'+name+'-sync')
            QTest.qWait(160)
            record(frame,'WM_SETTINGCHANGE-'+name+'-deferred')
        for event_type in (QEvent.Type.ThemeChange,QEvent.Type.WindowActivate,QEvent.Type.WindowDeactivate,QEvent.Type.ApplicationPaletteChange):
            QCoreApplication.sendEvent(frame,QEvent(event_type))
            QTest.qWait(160)
            record(frame,'qt-'+event_type.name)
        hwnd_before=int(frame.winId())
        frame.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        frame.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,False)
        record(frame,'flags-hidden')
        print(json.dumps(dict(tag='handle-recreated',changed=int(frame.winId())!=hwnd_before)),flush=True)
    finally:
        frame._unbind_window_screen()
        frame._close_ready=True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
