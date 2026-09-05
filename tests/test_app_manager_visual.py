"""应用管理列表的主题绘制与中文筛选契约。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionFrame, QStyleOptionViewItem, QWidget

from gui.dialogs.app_manager import AppManagerPage
from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.styles import BaseStyles
from gui.styles.fonts import FontMixin
from tests.ui_geometry_helpers import assert_scroll_target_reachable, wait_until


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_app_manager_rows_keep_readable_background_after_theme_switch(qt_application, theme):
    """主题切换后普通行与交替行均应使用当前主题的实色，不能残留反色条纹。"""
    previous_theme = BaseStyles.current_theme()
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([
            (f"示例 {row}", f"com.example.app{row}", "Enabled", "User")
            for row in range(4)
        ])
        page.resize(1000, 740)
        page.show()
        BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
        qt_application.processEvents()
        BaseStyles.switch_theme(theme)
        QTest.qWait(20)
        surface = page._master_panel.grab().toImage().pixelColor(0, 0)
        assert surface.alpha() == 255
        assert surface.lightness() > 220 if theme == "Light" else surface.lightness() < 70
        image = page.tree.viewport().grab().toImage()
        colors = []
        for row in range(4):
            rect = page.tree.visualRect(page.proxy.index(row, 1))
            color = image.pixelColor(rect.right() - 8, rect.center().y())
            assert color.alpha() == 255
            assert color.lightness() > 220 if theme == "Light" else color.lightness() < 70
            colors.append(color.lightness())
        assert 0 < abs(colors[0] - colors[1]) <= 20
    finally:
        page.close()
        BaseStyles.switch_theme(previous_theme)
        qt_application.processEvents()


def test_chinese_application_type_filter_preserves_source_values_and_selection(qt_application):
    """本地化仅作用于展示，状态源值、两种视图过滤与勾选集合保持一致。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([
            ("普通应用", "com.example.user", "Enabled", "User"),
            ("系统应用", "com.example.system", "Disabled", "System"),
        ])
        page.model.item(0, 0).setCheckState(Qt.CheckState.Checked)
        page.type_filter.setCurrentIndex(2)
        assert page.type_filter.currentText() == "系统应用"
        assert page.proxy.rowCount() == 1
        assert page.proxy.index(0, 2).data() == "com.example.system"
        assert page.proxy.index(0, 4).data() == "已停用"
        assert page.proxy.index(0, 5).data() == "系统"
        assert page.model.item(1, 4).text() == "Disabled"
        assert page.model.item(1, 5).text() == "System"
        visible = [
            page.icon_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(page.icon_list.count())
            if not page.icon_list.item(row).isHidden()
        ]
        assert visible == ["com.example.system"]
        assert page.selected_packages == {"com.example.user"}
    finally:
        page.close()


def test_operation_log_toggle_reclaims_space_without_losing_messages(qt_application):
    """操作记录默认收起，展开与再次收起均保留已追加内容并腾出列表空间。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page.resize(720, 600)
        page.show()
        qt_application.processEvents()
        page.log("第一条操作记录")
        collapsed_height = page.stack.height()
        assert not page.log_output.isVisibleTo(page)
        page.log_toggle.click()
        qt_application.processEvents()
        assert page.log_output.isVisibleTo(page)
        assert page.stack.height() < collapsed_height
        page.log("第二条操作记录")
        page.log_toggle.click()
        qt_application.processEvents()
        assert not page.log_output.isVisibleTo(page)
        assert page.stack.height() == collapsed_height
        assert "第一条操作记录" in page.log_output.toPlainText()
        assert "第二条操作记录" in page.log_output.toPlainText()
    finally:
        page.close()


def test_application_checkbox_keyboard_and_delegate_follow_page_font(qt_application):
    """替换局部绘制仍支持空格勾选，并按页面字体绘制而非上游固定字号。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([("示例应用", "com.example.app", "Enabled", "User")])
        page.resize(1000, 740)
        page.show()
        index = page.proxy.index(0, 0)
        page.tree.setCurrentIndex(index)
        page.tree.setFocus()
        QTest.keyClick(page.tree, Qt.Key.Key_Space)
        assert page.selected_packages == {"com.example.app"}
        QTest.keyClick(page.tree, Qt.Key.Key_Space)
        assert page.selected_packages == set()

        page.tree.setFont(QFont("Arial", 22))
        option = QStyleOptionViewItem()
        page.tree.itemDelegate().initStyleOption(option, page.proxy.index(0, 1))
        assert option.font.pointSize() == 22
    finally:
        page.close()


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("icon_mode", [False, True])
def test_small_workspace_keeps_complete_application_rows(
    qt_application, monkeypatch, font_size, icon_mode
):
    """窄工作区至少保留三条完整表格行或两行图标，后续动作交由外层滚动承接。"""
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda cls, role, size=None: QFont("Arial", size or font_size)),
    )
    page = AppManagerPage(device_ip="visual-demo")
    monkeypatch.setattr(page, "_load_apps", lambda: False)
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    page._populate([
        (f"示例应用 {row}", f"com.example.app{row}", "Enabled", "User")
        for row in range(24)
    ])
    host = WorkspaceFeatureHost("apps", "应用", QWidget())
    host.register_feature("manager", "应用管理", QIcon(), lambda key: page)
    host.set_device_context(["visual-demo"], ["visual-demo"])
    assert host.open_feature("manager")
    try:
        host.resize(720, 600)
        host.show()
        if icon_mode:
            page._toggle_view()
        QTest.qWait(50)
        wait_until(
            qt_application,
            lambda: page.height() >= page.workspace_content_minimum_size().height(),
        )
        if icon_mode:
            view = page.icon_list
            rows = {}
            for index in range(view.count()):
                rect = view.visualItemRect(view.item(index))
                rows.setdefault(rect.top(), rect)
            first_rows = [rows[top] for top in sorted(rows)[:2]]
            assert len(first_rows) == 2
            assert all(view.viewport().rect().contains(rect) for rect in first_rows)
        else:
            view = page.tree
            assert all(
                view.viewport().rect().contains(view.visualRect(page.proxy.index(row, 0)))
                for row in range(3)
            )
        assert_scroll_target_reachable(host.content_scroll, page.status_bar)
        assert host.width() == 720
        assert host.height() == 600
    finally:
        page.close()
        host.close()


@pytest.mark.parametrize("embedded", [False, True])
def test_manager_search_and_table_header_fit_large_text(qt_application, monkeypatch, embedded):
    """22pt 搜索文字须完整位于输入内容区，表头也使用当前界面字体。"""
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda cls, role, size=None: QFont("Arial", size or 22)),
    )
    page = AppManagerPage(device_ip="visual-demo")
    try:
        if embedded:
            page.prepare_for_workspace()
        page.resize(1000, 900)
        page.show()
        qt_application.processEvents()
        editor = page.search_input
        option = QStyleOptionFrame()
        editor.initStyleOption(option)
        content = editor.style().subElementRect(
            QStyle.SubElement.SE_LineEditContents, option, editor
        )
        margins = editor.textMargins()
        assert (
            content.height() - margins.top() - margins.bottom()
            >= QFontMetrics(editor.font()).height()
        )
        header_font = page.model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.FontRole)
        assert isinstance(header_font, QFont)
        assert header_font.pointSize() == 22
        assert page.tree.header().height() >= QFontMetrics(header_font).height()
    finally:
        page.close()


def test_workspace_preparation_moves_status_and_reclaims_duplicate_header(qt_application):
    """嵌入只移走一次内部页头，工具栏仍显示状态；独立页面保持完整标题。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page.resize(1000, 900)
        page.show()
        qt_application.processEvents()
        assert page.header_card.isVisibleTo(page)
        before = page.workspace_content_minimum_size().height()
        page.prepare_for_workspace()
        page.prepare_for_workspace()
        qt_application.processEvents()
        assert not page.header_card.isVisibleTo(page)
        assert page.status_badge.isVisibleTo(page)
        assert page.status_badge.parentWidget() is page._search_control
        assert page._search_control.layout().count() == 2
        assert page.workspace_content_minimum_size().height() < before
        page.set_device_connected(False)
        assert page.status_badge.text() == "离线"
        assert page.status_badge.isVisibleTo(page)
    finally:
        page.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_narrow_workspace_keeps_tools_visible_with_long_status(
    qt_application, monkeypatch, theme
):
    """500px 整窗对应的 404px 内容宽内，长状态句不能把工具栏推到视口之外。"""
    previous_theme = BaseStyles.current_theme()
    monkeypatch.setattr(
        FontMixin, "font_for_role",
        classmethod(lambda cls, role, size=None: QFont("Arial", size or 22)),
    )
    BaseStyles.switch_theme(theme)
    page = AppManagerPage(device_ip="visual-demo")
    monkeypatch.setattr(page, "_load_apps", lambda: False)
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    host = WorkspaceFeatureHost("apps", "应用", QWidget())
    host.register_feature("manager", "应用管理", QIcon(), lambda key: page)
    host.set_device_context(["visual-demo"], ["visual-demo"])
    assert host.open_feature("manager")
    try:
        page._populate([
            (f"示例应用 {row}", f"com.example.app{row}", "Enabled", "User")
            for row in range(24)
        ])
        host.setFixedSize(452, 640)
        host.show()
        QTest.qWait(50)
        viewport = host.content_scroll.viewport()
        assert viewport.width() == 404
        assert host.content_scroll.horizontalScrollBar().maximum() == 0
        for control in (*page._top_controls, page.search_input, page.status_badge):
            left = control.mapTo(viewport, QPoint()).x()
            assert 0 <= left
            assert left + control.width() <= viewport.width()
        assert page.tree.horizontalScrollBar().maximum() > 0
        assert "24" in page.status_bar.text()
        assert_scroll_target_reachable(host.content_scroll, page.status_bar)
    finally:
        page.close()
        host.close()
        BaseStyles.switch_theme(previous_theme)
        qt_application.processEvents()
