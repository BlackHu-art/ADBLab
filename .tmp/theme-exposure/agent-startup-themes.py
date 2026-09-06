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
from qfluentwidgets import isDarkTheme
sys.path.append(str(Path.cwd() / '.venv' / 'Lib' / 'site-packages'))
from tests.test_main_window_layout import _MainFrameSettings, build_main_frame

app = QApplication([])
getter = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute
getter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
getter.restype = ctypes.c_long

def attribute(frame, key):
    value = ctypes.c_int(-99)
    code = getter(int(frame.winId()), key, ctypes.byref(value), ctypes.sizeof(value))
    return [code, value.value]

def record(frame, tag, settings):
    print(json.dumps(dict(tag=tag, dark=attribute(frame,20), backdrop=attribute(frame,38),
        mode=BaseStyles.current_theme(), resolved=BaseStyles.resolved_theme(),
        qfluent_dark=isDarkTheme(), palette=app.palette().window().color().name(),
        setting=settings.get('theme'), qt_scheme=app.styleHints().colorScheme().name)), flush=True)

for initial in ('Dark','System','Light'):
    settings = _MainFrameSettings()
    settings.values.update(theme=initial, mica_enabled=True)
    with patch.object(AppSettings, 'instance', classmethod(lambda cls: settings)), patch.object(DeviceStore,'get_basic_devices_info',lambda:[]), patch.object(DeviceStore,'get_full_devices_info',lambda devices:[]):
        BaseStyles.switch_theme(initial)
        frame = build_main_frame(settings=settings)
        try:
            QTest.qWait(150)
            record(frame,initial+'-startup',settings)
            for index,target in enumerate(('Light','Dark','System','Dark','Light','Dark')):
                frame._settings_page._set_theme(frame._settings_page.THEME_LABELS[target])
                record(frame,f'{initial}-{index}-{target}-sync',settings)
                QTest.qWait(160)
                record(frame,f'{initial}-{index}-{target}-deferred',settings)
        finally:
            frame._unbind_window_screen()
            frame._close_ready=True
            frame.close()
            frame.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
