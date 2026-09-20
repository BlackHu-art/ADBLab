"""隔离瞬态 RoundMenu 行对象与页面长期共享动作的生命周期。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction
from qfluentwidgets import RoundMenu


class MenuActionProxy(QAction):
    """菜单独占的动作投影；状态取自源动作，触发仍由源动作负责。

    RoundMenu 会在 QAction 上保存单个行指针。代理避免临时行覆盖源动作在其它
    菜单中的指针；源信号接收者均为本 QObject，菜单销毁时 Qt 自动断开连接。
    """

    def __init__(self, source: QAction, menu: RoundMenu) -> None:
        super().__init__(menu)
        self._source: QAction | None = source
        # 快捷键仅用于菜单展示，不能再注册一份源动作的应用级快捷键。
        self.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._sync_source()
        source.changed.connect(self._sync_source)
        source.destroyed.connect(self._source_destroyed)
        self.triggered.connect(self._trigger_source)

    @Slot()
    def _sync_source(self) -> None:
        source = self._source
        if source is None:
            return
        self.setText(source.text())
        self.setIcon(source.icon())
        self.setToolTip(source.toolTip())
        self.setShortcut(source.shortcut())
        self.setData(source.data())
        self.setCheckable(source.isCheckable())
        self.setChecked(source.isChecked())
        self.setEnabled(source.isEnabled())
        self.setVisible(source.isVisible())

    @Slot()
    def _trigger_source(self) -> None:
        if self._source is not None:
            self._source.trigger()

    @Slot()
    def _source_destroyed(self) -> None:
        self._source = None
        self.setEnabled(False)


def add_shared_menu_action(menu: RoundMenu, source: QAction) -> MenuActionProxy:
    """加入菜单独占代理，保留源动作的父对象、行归属和唯一业务回调。"""
    proxy = MenuActionProxy(source, menu)
    menu.addAction(proxy)
    return proxy
