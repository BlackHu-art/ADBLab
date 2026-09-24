"""共享动作的瞬态菜单必须隔离第三方菜单行指针与对象生命周期。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget
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


@pytest.mark.parametrize("dismissal", ["escape", "owner"])
def test_keyboard_opened_menu_releases_on_escape_or_owner_deletion(
    qt_application, dismissal,
):
    """键盘打开的菜单仍可聚焦和取消，宿主销毁也在菜单子控件析构前归还焦点。"""
    owner = QWidget()
    owner.resize(400, 300)
    button = QPushButton("Open menu", owner)
    source = QAction("Shared", owner)
    callback = Mock()
    source.triggered.connect(callback)
    menu = create_transient_menu(owner)
    proxy = add_shared_menu_action(menu, source)
    button.clicked.connect(lambda: menu.exec(QPoint(20, 20), ani=False))
    try:
        owner.show()
        button.setFocus()
        qt_application.processEvents()
        QTest.keyClick(button, Qt.Key.Key_Space)
        qt_application.processEvents()
        assert menu.isVisible()
        menu.view.setFocus(Qt.FocusReason.TabFocusReason)
        assert menu.view.hasFocus()
        if dismissal == "escape":
            QTest.keyClick(menu, Qt.Key.Key_Escape)
            assert not menu.isVisible()
        else:
            owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(menu) and not isValid(proxy)
        callback.assert_not_called()
        if dismissal == "escape":
            assert isValid(source) and source.isEnabled()
        else:
            assert not isValid(owner) and not isValid(source)
    finally:
        if isValid(owner):
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


@pytest.mark.parametrize("focus_list", [False, True])
def test_mouse_click_releases_menu_focus_before_child_destruction(qt_application, focus_list):
    """迅速重开再鼠标点击时，待删菜单的迟到焦点也应在子列表析构前归还。"""
    owner = QWidget()
    owner.resize(400, 300)
    button = QPushButton("Owner", owner)
    source = QAction("Shared", owner)
    callback = Mock()
    source.triggered.connect(callback)
    source.triggered.connect(lambda: source.setEnabled(False))
    owner.show()
    button.setFocus()
    qt_application.processEvents()
    first_menu = create_transient_menu(owner)
    add_shared_menu_action(first_menu, source)
    first_menu.exec(QPoint(20, 20), ani=False)
    first_menu.close()
    menu = create_transient_menu(owner)
    add_shared_menu_action(menu, source)
    try:
        menu.exec(QPoint(20, 20), ani=False)
        qt_application.processEvents()
        if focus_list:
            menu.view.setFocus(Qt.FocusReason.TabFocusReason)
            assert menu.view.hasFocus()
        item_rect = menu.view.visualItemRect(menu.view.item(0))
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton, pos=item_rect.center(),
        )
        callback.assert_called_once()
        assert not menu.isVisible()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(menu)
        assert isValid(source) and not source.isEnabled()
    finally:
        # 失败也先在完整控件仍存活时归还焦点，保证回归以断言呈现而非进程崩溃。
        if isValid(menu):
            menu.view.clearFocus()
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
