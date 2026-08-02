"""协调设备、应用、系统和 Remote 子面板的延迟加载与信号连接。"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.panels.app_panel import AppPanel
from gui.panels.device_manager import DeviceManager
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.system_panel import SystemPanel
from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon


class SidePanel(QWidget):
    """创建并管理功能标签页，同时保持 MainFrame 使用的兼容接口。"""

    PANEL_WIDTH = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.signals = SidePanelSignals()
        self._package_history = []
        self._connected_device_cache = []
        self._user_selected_ip = False
        self._current_ip = ""
        self._tabs_connected = False
        self._connected_lazy_tabs = set()
        self._loaded_lazy_tabs = set()

        self.setMinimumWidth(300)
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        BaseStyles.theme_changed.connect(self._on_theme_changed)
        BaseStyles.fonts_changed.connect(self._on_fonts_changed)

        self._create_fonts()
        self._create_ui()
        self._connect_all_signals()

    # ── 字体 ─────────────────────────────────────────────────────────────

    def _create_fonts(self):
        # 兼容旧面板属性名；普通交互控件必须与全局界面字号保持一致。
        self._font_sm = BaseStyles.font_for_role(FontRole.UI)
        self._font_mono = BaseStyles.font_for_role(FontRole.MONO)
        self._font_base = BaseStyles.font_for_role(FontRole.UI)
        self._font_tab = BaseStyles.font_for_role(FontRole.UI)

    # ── 界面构建 ─────────────────────────────────────────────────────────

    def _create_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # 设备面板由 MainFrame 放入左栏；这里提前构建，确保初始化时可以连接信号。
        self._devices_tab = DeviceManager(self)
        self._device_widget = self._devices_tab.build_ui()

        self.tabs = QTabWidget()
        self.tabs.setFont(self._font_tab)
        self._apply_tab_style()

        self._apps_tab = None
        self._advanced_tab = None
        self._scrcpy_tab = None
        self._tab_scroll_areas = {}
        self._responsive_viewports = {}
        self._lazy_tab_specs = [
            ("_apps_tab", AppPanel, "Apps"),
            ("_advanced_tab", SystemPanel, "System"),
            ("_scrcpy_tab", RemotePanel, "Remote"),
        ]
        for index, (_attr, _cls, name) in enumerate(self._lazy_tab_specs):
            scroll = self._create_tab_scroll_area()
            self._tab_scroll_areas[index] = scroll
            self._responsive_viewports[scroll.viewport()] = index
            scroll.viewport().installEventFilter(self)
            self.tabs.addTab(scroll, name)
        self.tabs.currentChanged.connect(self._ensure_tab_loaded)
        self._ensure_tab_loaded(0)

        lo.addWidget(self.tabs, stretch=1)

    def _create_tab_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}\n{BaseStyles.SCROLLBAR_STYLE()}"
        )
        return scroll

    def _ensure_tab_loaded(self, index: int):
        if index < 0 or index >= len(self._lazy_tab_specs):
            return None
        attr, cls, _name = self._lazy_tab_specs[index]
        tab = getattr(self, attr, None)
        if tab is not None:
            return tab
        tab = cls(self)
        self._tab_scroll_areas[index].setWidget(tab.build_ui())
        setattr(self, attr, tab)
        self._loaded_lazy_tabs.add(index)
        apply_responsive_width = getattr(tab, "apply_responsive_width", None)
        if callable(apply_responsive_width):
            apply_responsive_width(self._tab_scroll_areas[index].viewport().width())
        if self._tabs_connected:
            self._connect_lazy_tab_signals(index, tab)
        return tab

    def eventFilter(self, watched, event):
        index = self._responsive_viewports.get(watched)
        if index is not None and event.type() == QEvent.Type.Resize:
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            apply_responsive_width = getattr(tab, "apply_responsive_width", None)
            if callable(apply_responsive_width):
                apply_responsive_width(event.size().width())
        return super().eventFilter(watched, event)

    def _connect_lazy_tab_signals(self, index: int, tab=None):
        if index in self._connected_lazy_tabs:
            return
        tab = tab or self._ensure_tab_loaded(index)
        if tab is None:
            return
        tab.connect_signals()
        self._connected_lazy_tabs.add(index)

    # ── 委托给子标签页的共享属性 ─────────────────────────────────────────

    @property
    def selected_devices(self) -> list[str]:
        return self._devices_tab.selected_devices

    @property
    def ip_address(self) -> str:
        return self._devices_tab.ip_address

    @property
    def device_widget(self) -> QWidget:
        return self._device_widget

    # ── MainFrame 使用的公共接口 ─────────────────────────────────────────

    def update_device_list(self, devices: list[str] = None):
        self._devices_tab.update_device_list(devices)

    def refresh_device_choices(self):
        self._devices_tab._refresh_device_combobox()

    def apply_device_theme(self):
        self._devices_tab._apply_device_list_style()
        if hasattr(self._devices_tab, "ip_entry"):
            self._apply_completer_style(self._devices_tab.ip_entry.completer())

    def apply_responsive_widths(self, left_width: int, _right_width: int) -> None:
        """刷新分栏布局；功能页始终以各自 viewport 实际宽度为准。"""

        self._devices_tab.apply_responsive_width(left_width)
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            callback = getattr(tab, "apply_responsive_width", None)
            if callable(callback):
                callback(self._tab_scroll_areas[index].viewport().width())

    def current_package_text(self) -> str:
        apps_tab = self._apps_tab
        if apps_tab is None:
            return ""
        return apps_tab.package_text

    def update_current_package(self, device_ip: str, package_name: str):
        self._devices_tab.update_current_package(device_ip, package_name)

    def update_email(self, t: str):
        self._ensure_tab_loaded(0).update_email(t)

    def update_vercode(self, t: str):
        self._ensure_tab_loaded(0).update_vercode(t)

    def on_recording_finished(self):
        apps_tab = self._ensure_tab_loaded(0)
        if apps_tab:
            apps_tab.on_recording_finished()

    def on_operation_completed(self, operation: str, success: bool, message: str):
        apps_tab = self._ensure_tab_loaded(0)
        if apps_tab:
            apps_tab.on_operation_completed(operation, success, message)

    def shutdown(self):
        """依次关闭已加载标签页拥有的后台资源。"""
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            shutdown = getattr(tab, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def register_shutdown_tasks(self, supervisor, *, owner_id: str) -> tuple[str, ...]:
        """将已加载标签页的异步关闭任务注册到统一监督器。"""
        registered = []
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            register = getattr(tab, "register_shutdown_task", None)
            if not callable(register):
                continue
            task_id = f"{owner_id}-panel-{index}"
            if register(supervisor, owner_id=owner_id, task_id=task_id):
                registered.append(task_id)
        return tuple(registered)

    # ── 主题 ─────────────────────────────────────────────────────────────

    def _apply_tab_style(self):
        bs = BaseStyles
        self.tabs.setStyleSheet(
            f"""QTabWidget::pane{{border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_MD}px;background:{bs.color('WINDOW_BG')};}}QTabBar::tab{{background:{bs.color('BUTTON_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-bottom:none;padding:3px 12px;border-radius:{bs.RADIUS_SM}px {bs.RADIUS_SM}px 0 0;margin-right:1px;}}QTabBar::tab:selected{{background:{bs.color('WINDOW_BG')};border-bottom:2px solid {bs.color('BUTTON_ACCENT')};}}QTabBar::tab:hover{{background:{bs.color('BUTTON_HOVER')};}}"""
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
            f"QListView{{background-color:{bs.color('INPUT_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_SM}px;padding:2px;outline:none;}}QListView::item{{padding:4px 8px;}}QListView::item:selected{{background-color:{bs.color('SELECTION_BG')};color:{bs.color('SELECTION_TEXT')};}}QListView::item:hover{{background-color:{bs.color('BUTTON_HOVER')};}}"
        )

    def _on_theme_changed(self, _):
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        self._apply_tab_style()
        scrollbar_qss = BaseStyles.SCROLLBAR_STYLE()
        group_qss = BaseStyles.GROUP_BOX_STYLE()
        # 单次遍历控件树，避免为每种控件分别调用 findChildren。
        for child in self.findChildren(QWidget):
            if isinstance(child, QGroupBox):
                child.setStyleSheet(group_qss)
            elif isinstance(child, QPushButton):
                variant = child.property("buttonVariant")
                if variant:
                    child.setObjectName(str(variant))
                    child.setStyleSheet(BaseStyles.BUTTON_QSS())
                    child.style().unpolish(child)
                    child.style().polish(child)
                icon_name = child.property("iconName")
                if icon_name:
                    child.setIcon(get_themed_icon(icon_name))
            elif isinstance(child, QScrollArea):
                child.setStyleSheet(
                    f"QScrollArea {{ border: none; background: transparent; }}\n{scrollbar_qss}"
                )
        self.apply_device_theme()
        if self._apps_tab is not None and hasattr(self._apps_tab, "completer"):
            self._apply_completer_style(self._apps_tab.completer)

    def _on_fonts_changed(self, _config):
        """字体配置变化时更新已创建控件，不借用主题刷新路径。"""

        self._create_fonts()
        self.setFont(self._font_base)
        self.tabs.setFont(self._font_tab)
        group_qss = BaseStyles.GROUP_BOX_STYLE()
        roots = [self]
        device_widget = getattr(self, "_device_widget", None)
        if device_widget is not None and not self.isAncestorOf(device_widget):
            roots.append(device_widget)
        for root in roots:
            root.setFont(self._font_base)
            for child in root.findChildren(QWidget):
                role = child.property("fontRole")
                if role:
                    try:
                        child.setFont(BaseStyles.font_for_role(role))
                    except ValueError:
                        child.setFont(self._font_base)
                if isinstance(child, QGroupBox):
                    # 分组标题净空依赖当前字体度量，字号变化后必须同步刷新 QSS。
                    child.setStyleSheet(group_qss)
        self._devices_tab.apply_fonts()
        self._apply_completer_style(
            self._apps_tab.completer if self._apps_tab is not None else None
        )

    # ── 信号连接 ──────────────────────────────────────────────────────────

    def _connect_all_signals(self):
        """委托各标签页连接各自的信号。"""
        self._devices_tab.connect_signals()
        self._tabs_connected = True
        for index in sorted(self._loaded_lazy_tabs):
            self._connect_lazy_tab_signals(index)
