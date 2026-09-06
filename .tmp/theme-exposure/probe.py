import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd()))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core.settings_manager import AppSettings
from models.device_store import DeviceStore
from gui.styles import BaseStyles
from tests.test_main_window_layout import _MainFrameSettings, build_main_frame

app = QApplication([])
settings = _MainFrameSettings()
settings.values.update(theme='Light', mica_enabled=True, window_width=860, window_height=950)
output = Path('.tmp/theme-exposure')
getter = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute
getter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
getter.restype = ctypes.c_long

def attribute(frame, key):
    value = ctypes.c_int(-99)
    code = getter(int(frame.winId()), key, ctypes.byref(value), ctypes.sizeof(value))
    return [code, value.value]

def capture(frame, tag):
    # 仅抓取本探针窗口的客户区，避免采集桌面或其他窗口。
    origin = frame.mapToGlobal(QPoint(0, 0))
    image = frame.screen().grabWindow(0, origin.x(), origin.y(), frame.width(), frame.height()).toImage()
    image.save(str(output / f'{tag}.png'))
    scale = image.devicePixelRatio()
    point = frame._content_surface.mapTo(frame, QPoint(300, 30))
    record = dict(tag=tag, dark=attribute(frame,20), backdrop=attribute(frame,38),
        qt=app.styleHints().colorScheme().name, theme=BaseStyles.resolved_theme(),
        background=frame.backgroundColor.getRgb(), pixel=image.pixelColor(round(point.x()*scale),round(point.y()*scale)).getRgb())
    print(json.dumps(record), flush=True)

with patch.object(AppSettings, 'instance', classmethod(lambda cls: settings)), patch.object(DeviceStore,'get_basic_devices_info',lambda:[]), patch.object(DeviceStore,'get_full_devices_info',lambda devices:[]):
    BaseStyles.switch_theme('Light')
    frame = build_main_frame(settings=settings)
    try:
        frame.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        frame.move(80, 40)
        frame.show()
        frame.raise_()
        frame.activateWindow()
        frame._on_nav_requested('settings')
        QTest.qWait(450)
        capture(frame, 'native-before-light')
        for i, theme in enumerate(('Dark','Light','Dark')):
            BaseStyles.switch_theme(theme)
            capture(frame,f'native-before-{i}-{theme}-0')
            for delay in (20,50,100,250,600):
                QTest.qWait(delay)
                capture(frame,f'native-before-{i}-{theme}-{delay}')
    finally:
        frame._unbind_window_screen()
        frame._close_ready=True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
