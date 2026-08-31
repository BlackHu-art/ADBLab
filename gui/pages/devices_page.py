"""设备页：包装既有 DeviceManager 控件，保持其全部公开行为。

``DevicesPage`` 只是一个页面宿主：它持有并布局 ``DeviceManager.build_ui()``
返回的视觉根，其余公开属性 / 方法（``update_device_list``、``set_discovery_state``、
``selected_devices``、``ip_address``、``connect_signals`` 等）通过 ``__getattr__``
直接委托给内部 ``DeviceManager``，不复制也不改写任何行为。
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.panels.device_manager import DeviceManager

__all__ = ["DevicesPage"]


class DevicesPage(QWidget):
    """设备页宿主；内部持有 :class:`~gui.panels.device_manager.DeviceManager`。"""

    def __init__(self, panel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("devicesPage")
        # DeviceManager 依赖 SidePanel 兼容接口（signals / 字体 / 响应式协调器），
        # 因此保留 ``panel`` 参数，与 SidePanel 直接实例化 DeviceManager 的路径一致。
        self._manager = DeviceManager(panel, parent=self)
        root = self._manager.build_ui()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(root)

    @property
    def device_manager(self) -> DeviceManager:
        """返回被包装的 DeviceManager 实例。"""

        return self._manager

    @property
    def root_widget(self) -> QWidget:
        """返回 DeviceManager 构建的视觉根控件。"""

        return self._manager.device_widget

    def __getattr__(self, name: str):
        """把未定义属性委托给内部 DeviceManager，保持全部公开行为。"""

        manager = self.__dict__.get("_manager")
        if name.startswith("_") or manager is None:
            raise AttributeError(name)
        return getattr(manager, name)
