"""验证页面内功能导航的同步、响应式形态和无障碍契约。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from qfluentwidgets import FluentIcon, ListWidget

from gui.styles import BaseStyles
from gui.widgets.area_navigation import AreaNavigationRail


def _navigation() -> AreaNavigationRail:
    navigation = AreaNavigationRail()
    navigation.add_item("devices", "连接与选择", FluentIcon.PHONE)
    navigation.add_item("files", "文件管理", FluentIcon.FOLDER)
    navigation.add_item("remote", "远程控制", FluentIcon.PROJECTOR)
    return navigation


def test_first_item_initializes_both_navigation_modes(qt_application):
    navigation = _navigation()
    try:
        assert isinstance(navigation.list_widget, ListWidget)
        assert navigation.rail is navigation.list_widget
        assert navigation.keys == ("devices", "files", "remote")
        assert navigation.current_key == "devices"
        assert navigation.list_widget.currentRow() == 0
        assert navigation.combo.currentIndex() == 0
        assert navigation.combo.currentData() == "devices"
        assert navigation.list_widget.item(0).data(Qt.ItemDataRole.UserRole) == "devices"
        assert not navigation.list_widget.item(0).icon().isNull()
    finally:
        navigation.close()


def test_list_combo_and_programmatic_changes_emit_once(qt_application):
    navigation = _navigation()
    changes = QSignalSpy(navigation.current_changed)
    try:
        navigation.list_widget.setCurrentRow(1)
        assert navigation.current_key == "files"
        assert navigation.combo.currentData() == "files"
        assert changes.count() == 1
        assert changes.at(0) == ["files"]

        navigation.combo.setCurrentIndex(2)
        assert navigation.current_key == "remote"
        assert navigation.list_widget.currentRow() == 2
        assert changes.count() == 2
        assert changes.at(1) == ["remote"]

        assert navigation.set_current("devices") is True
        assert navigation.set_current("devices") is True
        assert navigation.current_key == "devices"
        assert navigation.list_widget.currentRow() == 0
        assert navigation.combo.currentData() == "devices"
        assert changes.count() == 3
        assert changes.at(2) == ["devices"]
    finally:
        navigation.close()


def test_unknown_key_does_not_change_selection_or_emit(qt_application):
    navigation = _navigation()
    changes = QSignalSpy(navigation.current_changed)
    try:
        before_row = navigation.list_widget.currentRow()
        before_combo = navigation.combo.currentIndex()

        assert navigation.set_current("missing") is False
        assert navigation.current_key == "devices"
        assert navigation.list_widget.currentRow() == before_row
        assert navigation.combo.currentIndex() == before_combo
        assert changes.count() == 0
    finally:
        navigation.close()


def test_navigation_uses_labeled_combo_below_compact_width(qt_application):
    navigation = _navigation()
    try:
        navigation.resize(navigation.COMPACT_WIDTH - 1, 360)
        navigation.show()
        qt_application.processEvents()

        assert navigation.compact_widget.isVisibleTo(navigation)
        assert navigation.current_label.text() == "当前功能"
        assert navigation.combo.isVisibleTo(navigation)
        assert navigation.list_widget.isHidden()

        navigation.resize(navigation.COMPACT_WIDTH, 360)
        qt_application.processEvents()

        assert navigation.list_widget.isVisibleTo(navigation)
        assert navigation.compact_widget.isHidden()
        assert navigation.current_key == "devices"
    finally:
        navigation.close()


def test_host_available_width_controls_rail_mode(qt_application):
    navigation = _navigation()
    try:
        navigation.resize(220, 360)
        navigation.set_available_width(1024)
        navigation.show()
        qt_application.processEvents()

        assert navigation.list_widget.isVisibleTo(navigation)
        assert navigation.compact_widget.isHidden()

        navigation.set_available_width(720)
        qt_application.processEvents()
        assert navigation.list_widget.isHidden()
        assert navigation.compact_widget.isVisibleTo(navigation)
    finally:
        navigation.close()


def test_navigation_exposes_accessible_names_and_tooltips(qt_application):
    navigation = _navigation()
    try:
        assert navigation.accessibleName()
        assert navigation.toolTip()
        assert navigation.list_widget.accessibleName() == "功能导航"
        assert navigation.list_widget.toolTip() == "选择当前功能"
        assert navigation.combo.accessibleName() == "当前功能"
        assert navigation.combo.toolTip() == "选择当前功能"
        assert navigation.list_widget.item(1).toolTip() == "切换到“文件管理”"
    finally:
        navigation.close()


def test_navigation_rebuilds_fluent_icons_after_theme_change(qt_application):
    original_theme = BaseStyles.current_theme()
    navigation = _navigation()
    try:
        before = navigation.list_widget.item(0).icon().cacheKey()
        BaseStyles.switch_theme("Dark" if original_theme != "Dark" else "Light")
        qt_application.processEvents()
        after = navigation.list_widget.item(0).icon().cacheKey()

        assert after != before
        assert navigation.combo.itemIcon(0).cacheKey() == after
    finally:
        navigation.close()
        BaseStyles.switch_theme(original_theme)


def test_empty_duplicate_keys_labels_and_unsupported_icons_are_rejected(
    qt_application,
):
    navigation = AreaNavigationRail()
    try:
        navigation.add_item("devices", "连接与选择")
        with pytest.raises(ValueError, match="navigation key"):
            navigation.add_item(" ", "空键")
        with pytest.raises(ValueError, match="duplicate area navigation key"):
            navigation.add_item(" devices ", "重复")
        with pytest.raises(ValueError, match="label"):
            navigation.add_item("empty-label", " ")
        with pytest.raises(TypeError, match="unsupported area navigation icon"):
            navigation.add_item("bad-icon", "坏图标", object())

        assert navigation.keys == ("devices",)
    finally:
        navigation.close()
