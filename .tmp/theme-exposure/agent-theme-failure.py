import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core.settings_manager import AppSettings
from models.device_store import DeviceStore
from gui.styles import BaseStyles
# IDE venv 没有 pytest；仅让测试替身模块找到主项目开发工具，Qt 已从 IDE venv 载入。
sys.path.append(str(Path.cwd() / '.venv' / 'Lib' / 'site-packages'))
from tests.test_main_window_layout import _MainFrameSettings, build_main_frame
from qfluentwidgets import isDarkTheme

app = QApplication([])
settings = _MainFrameSettings()
settings.values.update(theme='Light', mica_enabled=True)
getter = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute
getter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
getter.restype = ctypes.c_long

def attribute(frame, key):
    value = ctypes.c_int(-99)
    code = getter(int(frame.winId()), key, ctypes.byref(value), ctypes.sizeof(value))
    return [code, value.value]

def record(frame, tag):
    print(json.dumps(dict(tag=tag, dark=attribute(frame,20), backdrop=attribute(frame,38),
        mode=BaseStyles.current_theme(), resolved=BaseStyles.resolved_theme(),
        qfluent_dark=isDarkTheme(), palette=app.palette().window().color().name(),
        pending_setting=settings.get('theme'))), flush=True)

with patch.object(AppSettings, 'instance', classmethod(lambda cls: settings)), patch.object(DeviceStore,'get_basic_devices_info',lambda:[]), patch.object(DeviceStore,'get_full_devices_info',lambda devices:[]):
    BaseStyles.switch_theme('Light')
    frame = build_main_frame(settings=settings)
    try:
        QTest.qWait(150)
        record(frame,'light-start')
        # 仅注入一次故障验证状态分叉机制；不据此假定用户实例出现了同一异常。
        with patch('qfluentwidgets.setThemeColor', side_effect=ValueError('probe-fault-after-theme-qss')):
            try:
                BaseStyles.switch_theme('Dark')
            except ValueError as exc:
                print(type(exc).__name__, str(exc), flush=True)
        record(frame,'failure-sync')
        QTest.qWait(160)
        record(frame,'failure-after-delayed-refresh')
        print(json.dumps(dict(theme_modules=[key for key in sys.modules if key == 'theme' or key.endswith('.styles.theme')])),flush=True)
    finally:
        frame._unbind_window_screen()
        frame._close_ready=True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
