"""左侧控制面板 — 五标签页容器，协调 Devices / Apps / Input & Diag / Advanced / Scrcpy。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.panels.app_panel import AppPanel
from gui.panels.device_manager import DeviceManager
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.system_panel import SystemPanel
from gui.styles.base_styles import BaseStyles


class SidePanel(QWidget):
    """左侧面板 — 创建并管理 5 个Function tabs。"""

    PANEL_WIDTH = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.signals = SidePanelSignals()
        self._package_history = []
        self._connected_device_cache = []
        self._user_selected_ip = False
        self._current_ip = ""

        self.setMinimumWidth(300)
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        BaseStyles.theme_changed.connect(self._on_theme_changed)

        self._create_fonts()
        self._create_ui()
        self._connect_all_signals()

    # ── Font ──────────────────────────────────────────────────────────────

    def _create_fonts(self):
        F = BaseStyles.DEFAULT_FONT_FAMILY
        ui_size = BaseStyles.DEFAULT_FONT_SIZE
        self._font_sm = QFont(F, ui_size)
        self._font_mono = QFont("Courier New", max(8, ui_size - 2))
        self._font_mono.setStyleHint(QFont.Monospace)
        self._font_base = QFont(F, ui_size)
        self._font_tab = QFont(F, ui_size)

    # ── UI construction ───────────────────────────────────────────────────────────

    def _create_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # Device manager (UI placed by MainFrame in left column，先构建以便 connect_signals）
        self._devices_tab = DeviceManager(self)
        self._device_widget = self._devices_tab.build_ui()

        # Function tabs
        self.tabs = QTabWidget()
        self.tabs.setFont(self._font_tab)
        self._apply_tab_style()

        self._apps_tab = AppPanel(self)
        self._advanced_tab = SystemPanel(self)
        self._scrcpy_tab = RemotePanel(self)

        tab_specs = [
            (self._apps_tab, "Apps"),
            (self._advanced_tab, "System"),
            (self._scrcpy_tab, "Remote"),
        ]
        for tab, name in tab_specs:
            s = QScrollArea()
            s.setWidgetResizable(True)
            s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            s.setStyleSheet(
                f"QScrollArea {{ border: none; background: transparent; }}\n{BaseStyles.SCROLLBAR_STYLE()}"
            )
            s.setWidget(tab.build_ui())
            self.tabs.addTab(s, name)

        lo.addWidget(self.tabs, stretch=1)

    # ── Shared properties（委托给子标签页）──────────────────────────────────────────

    @property
    def selected_devices(self) -> list[str]:
        return self._devices_tab.selected_devices

    @property
    def ip_address(self) -> str:
        return self._devices_tab.ip_address

    # ── Public methods（MainFrame 调用）──────────────────────────────────────────

    def update_device_list(self, devices: list[str] = None):
        self._devices_tab.update_device_list(devices)

    def _refresh_device_combobox(self):
        self._devices_tab._refresh_device_combobox()

    def update_current_package(self, device_ip: str, package_name: str):
        self._devices_tab.update_current_package(device_ip, package_name)

    def update_email(self, t: str):
        self._apps_tab.update_email(t)

    def update_vercode(self, t: str):
        self._apps_tab.update_vercode(t)

    # ── Theme ──────────────────────────────────────────────────────────────

    def _apply_tab_style(self):
        bs = BaseStyles
        self.tabs.setStyleSheet(
            f"""QTabWidget::pane{{border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_MD}px;background:{bs.color('WINDOW_BG')};}}QTabBar::tab{{background:{bs.color('BUTTON_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-bottom:none;padding:3px 12px;font-size:{bs.DEFAULT_FONT_SIZE}px;border-radius:{bs.RADIUS_SM}px {bs.RADIUS_SM}px 0 0;margin-right:1px;}}QTabBar::tab:selected{{background:{bs.color('WINDOW_BG')};border-bottom:2px solid {bs.color('BUTTON_ACCENT')};}}QTabBar::tab:hover{{background:{bs.color('BUTTON_HOVER')};}}"""
        )

    def _apply_completer_style(self, c):
        """为 Devices/Apps 标签页的 QCompleter 弹窗应用样式。"""
        if c is None:
            return
        p = c.popup()
        if p is None:
            return
        p.setFont(self._font_mono)
        bs = BaseStyles
        p.setStyleSheet(
            f"QListView{{background-color:{bs.color('INPUT_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_SM}px;padding:2px;outline:none;font-family:'Courier New',monospace;}}QListView::item{{padding:4px 8px;}}QListView::item:selected{{background-color:{bs.color('SELECTION_BG')};color:{bs.color('SELECTION_TEXT')};}}QListView::item:hover{{background-color:{bs.color('BUTTON_HOVER')};}}"
        )

    def _on_theme_changed(self, _):
        self._create_fonts()
        self.tabs.setFont(self._font_tab)
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        self._apply_tab_style()
        scrollbar_qss = BaseStyles.SCROLLBAR_STYLE()
        group_qss = BaseStyles.GROUP_BOX_STYLE()
        # Single tree traversal instead of 8 separate findChildren calls
        for child in self.findChildren(QWidget):
            t = type(child)
            if t is QGroupBox:
                child.setStyleSheet(group_qss)
                child.setFont(self._font_base)
            elif t is QPushButton:
                if not child.parent() or child.parent().objectName() != "toolbar":
                    child.setFont(self._font_sm)
            elif t is QLineEdit:
                child.setFont(self._font_sm)
            elif t is QComboBox:
                child.setFont(self._font_sm)
            elif t is QCheckBox:
                child.setFont(self._font_sm)
            elif t is QSlider:
                child.setFont(self._font_sm)
            elif t is QScrollArea:
                child.setStyleSheet(
                    f"QScrollArea {{ border: none; background: transparent; }}\n{scrollbar_qss}"
                )
        self._devices_tab._apply_device_list_style()
        if hasattr(self._devices_tab, "ip_entry"):
            self._apply_completer_style(self._devices_tab.ip_entry.completer())
        if hasattr(self._apps_tab, "completer"):
            self._apply_completer_style(self._apps_tab.completer)

    # ── 信号连接 ──────────────────────────────────────────────────────────

    def _connect_all_signals(self):
        """委托各标签页连接各自的信号。"""
        self._devices_tab.connect_signals()
        self._apps_tab.connect_signals()
        self._advanced_tab.connect_signals()
        self._scrcpy_tab.connect_signals()
