"""共享动作的瞬态菜单必须隔离第三方菜单行指针与对象生命周期。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import QWidget
from qfluentwidgets.components.widgets.command_bar import CommandMenu
from shiboken6 import isValid

from gui.styles.fluent import create_transient_menu
from gui.widgets.transient_menu import add_shared_menu_action

pytestmark = pytest.mark.ui


def test_transient_menu_does_not_replace_existing_command_menu_item(qt_application):
    owner = QWidget()
    source = QAction("Shared", owner)
    old_menu = CommandMenu(owner)
    old_menu.addAction(source)
    original_item = source.property("item")
    menu = create_transient_menu(owner)
    try:
        proxy = add_shared_menu_action(menu, source)
        assert source.property("item") is original_item
        assert proxy is not source
        menu.exec(QPoint(20, 20), ani=False)
        menu.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(proxy)
        assert isValid(source) and source.parent() is owner
        source.setEnabled(False)
        source.setText("Still alive")
        assert original_item.text().strip() == "Still alive"
        assert not original_item.flags() & Qt.ItemFlag.ItemIsEnabled
    finally:
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_proxy_tracks_source_state_without_registering_global_shortcut(qt_application):
    owner = QWidget()
    source = QAction("Shared", owner)
    source.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    menu = create_transient_menu(owner)
    proxy = add_shared_menu_action(menu, source)
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("red"))
    source.setText("Updated")
    source.setIcon(QIcon(pixmap))
    source.setToolTip("Shared tooltip")
    source.setShortcut(QKeySequence("Ctrl+K"))
    source.setData({"operation": "copy"})
    source.setCheckable(True)
    source.setChecked(True)
    source.setEnabled(False)
    assert proxy.text() == "Updated"
    assert proxy.icon().cacheKey() == source.icon().cacheKey()
    assert proxy.toolTip() == "Shared tooltip"
    assert proxy.shortcut() == source.shortcut()
    assert proxy.shortcutContext() == Qt.ShortcutContext.WidgetShortcut
    assert source.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut
    assert proxy.data() == {"operation": "copy"}
    assert proxy.isCheckable() and proxy.isChecked()
    assert not proxy.isEnabled()
    assert source.property("item") is None
    assert menu.view.item(0).text().strip() == "Updated"
    assert not menu.view.item(0).flags() & Qt.ItemFlag.ItemIsEnabled


def test_multiple_menu_proxies_trigger_source_once_and_release_connections(qt_application):
    owner = QWidget()
    source = QAction("Shared", owner)
    source.setCheckable(True)
    calls = Mock()
    source.triggered.connect(lambda checked: calls(checked))
    first_menu = create_transient_menu(owner)
    second_menu = create_transient_menu(owner)
    first = add_shared_menu_action(first_menu, source)
    second = add_shared_menu_action(second_menu, source)
    first.trigger()
    calls.assert_called_once_with(True)
    assert source.isChecked() and first.isChecked() and second.isChecked()
    first_menu.exec(QPoint(20, 20), ani=False)
    first_menu.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(first)
    source.setText("After close")
    assert second.text() == "After close"
    second.trigger()
    assert calls.call_count == 2
    assert calls.call_args.args == (False,)
    assert not source.isChecked() and not second.isChecked()
    assert source.property("item") is None


def test_source_deletion_disables_remaining_proxy(qt_application):
    owner = QWidget()
    source = QAction("Shared", owner)
    menu = create_transient_menu(owner)
    proxy = add_shared_menu_action(menu, source)
    source.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(source)
    assert isValid(proxy) and not proxy.isEnabled()
    proxy.trigger()


def test_clicking_proxy_closes_menu_and_runs_source_callback_once(qt_application):
    owner = QWidget()
    source = QAction("Shared", owner)
    callback = Mock()
    source.triggered.connect(callback)
    menu = create_transient_menu(owner)
    proxy = add_shared_menu_action(menu, source)
    menu.exec(QPoint(20, 20), ani=False)
    menu._onItemClicked(menu.view.item(0))
    callback.assert_called_once()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(menu) and not isValid(proxy)
    assert isValid(source)
