import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd()))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core.settings_manager import AppSettings
from models.device_store import DeviceStore
from unittest.mock import Mock
from core.settings_manager import DEFAULTS

class _MainFrameSettings:
    save_directory = '.'

    def __init__(self):
        self.values = {'window_width': 1120, 'window_height': 640, 'left_panel_width': 400, 'right_panel_width': 600, 'panel_split_ratio': 0.4, 'device_log_split_ratio': 0.6, 'always_on_top': False, 'log_max_lines': 2000}
        self.writes = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.writes.append({key: value})

    def set_many(self, values):
        values = dict(values)
        self.values.update(values)
        self.writes.append(values)

    def reset(self):
        self.values = dict(DEFAULTS)
        self.writes.append({'reset': True})

def build_main_frame(*, screen_adapter=None, settings=None, mouse_buttons_provider=None, controller=None):
    """用本地依赖替身构造 MainFrame，不访问 ADB 或外部 helper。"""
    settings = settings or _MainFrameSettings()
    if controller is None:
        controller = Mock()
        controller.signals = Mock()
    controller.operation_manager.active_snapshot.return_value = ()
    with patch.object(AppSettings, 'instance', classmethod(lambda _cls: settings)), patch('gui.main_frame.ADBController', lambda _log_service: controller), patch.object(MainFrame, '_bootstrap_adb_async', lambda _self: None):
        return MainFrame(screen_adapter=screen_adapter, mouse_buttons_provider=mouse_buttons_provider)

from main import windows_app_user_model_id
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(windows_app_user_model_id())
from gui.i18n import install_translators
app = QApplication([])
from utils.resource_path import setup_qt_search_paths
setup_qt_search_paths()
translators = install_translators(app, 'zh_CN')
from gui.main_frame import MainFrame
from gui.styles import BaseStyles
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
    from gui.i18n import install_translators
    BaseStyles.reload_from_settings()
    BaseStyles.set_accent_color('#0F6CBD')
    BaseStyles.switch_theme('Light')
    frame = build_main_frame(settings=settings)
    def exercise():
        try:
            frame.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            frame.move(80, 40)
            frame.show()
            frame.raise_()
            frame.activateWindow()
            frame._on_nav_requested('settings')
            QTest.qWait(450)
            capture(frame, 'native-before-light')
            combo = frame._settings_page.theme_card.combo_box
            for i, theme in enumerate(('Dark', 'Light', 'Dark')):
                QTest.mouseClick(combo, Qt.MouseButton.LeftButton)
                QTest.qWait(200)
                menu = combo.dropMenu
                row = combo.findText(frame._settings_page.THEME_LABELS[theme])
                item = menu.view.item(row)
                QTest.mouseClick(menu.view.viewport(), Qt.MouseButton.LeftButton, pos=menu.view.visualItemRect(item).center())
                QTest.qWait(350)
                capture(frame, f'event-loop-combo-{i}-{theme}')
            import win32gui
            for message in (0x001A, 0x031A, 0x0086, 0x0006):
                win32gui.SendMessage(int(frame.winId()), message, 0, 0)
                QTest.qWait(350)
                capture(frame, f'message-{message}')
            frame.showMinimized()
            QTest.qWait(200)
            frame.showNormal()
            QTest.qWait(400)
            capture(frame, 'restore')
        finally:
            frame._unbind_window_screen()
            frame._close_ready=True
            frame.close()
            frame.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    
            app.quit()
    QTimer.singleShot(0, exercise)
    app.exec()
