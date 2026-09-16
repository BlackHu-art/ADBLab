"""应用管理列表的主题绘制与中文筛选契约。"""

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionFrame, QStyleOptionViewItem, QWidget

from gui.dialogs.app_manager import AppManagerPage
from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.styles import BaseStyles
from gui.styles.fonts import FontMixin
from tests.ui_geometry_helpers import assert_scroll_target_reachable, wait_until


@pytest.mark.ui
def test_icon_view_has_four_independent_resizable_columns(qt_application):
    """图标只占首列，名称、包名和状态有独立模型列及可拖动边界。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([("示例应用", "com.example.app", "Enabled", "User")])
        page._toggle_view()
        page.resize(1000, 800)
        page.show()
        qt_application.processEvents()
        view = page.icon_list
        assert all(view.model().index(0, column).isValid() for column in range(4))
        assert not view.model().index(0, 4).isValid()
        item = view.topLevelItem(0)
        assert [item.text(column) for column in range(4)] == [
            "", "示例应用", "com.example.app", "已启用",
        ]
        assert not item.icon(0).isNull()
        assert all(item.icon(column).isNull() for column in range(1, 4))
        header = view.header()
        assert not header.isHidden()
        assert all(
            header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive
            for column in range(4)
        )
        assert all(not view.isColumnHidden(column) for column in range(4))
        before_width = header.sectionSize(1)
        before_package_x = view.visualRect(view.model().index(0, 2)).left()
        boundary = QPoint(
            header.sectionViewportPosition(1) + before_width - 1, header.height() // 2,
        )
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, pos=boundary)
        QTest.mouseMove(header.viewport(), boundary + QPoint(70, 0))
        QTest.mouseRelease(
            header.viewport(), Qt.MouseButton.LeftButton, pos=boundary + QPoint(70, 0),
        )
        qt_application.processEvents()
        assert abs(header.sectionSize(1) - before_width - 70) <= 2
        assert abs(view.visualRect(view.model().index(0, 2)).left() - before_package_x - 70) <= 2
    finally:
        page.close()


@pytest.mark.ui
def test_icon_column_widths_survive_theme_toggle_and_refresh(qt_application):
    """用户调整的四列宽度不被主题刷新、视图切换或数据刷新覆盖。"""
    previous_theme = BaseStyles.current_theme()
    page = AppManagerPage(device_ip="visual-demo")
    try:
        apps = [("示例应用", "com.example.app", "Enabled", "User")]
        page._populate(apps)
        page._toggle_view()
        page.resize(1000, 800)
        page.show()
        qt_application.processEvents()
        view = page.icon_list
        assert all(view.model().index(0, column).isValid() for column in range(4))
        assert not view.model().index(0, 4).isValid()
        expected = [72, 280, 360, 140]
        for column, width in enumerate(expected):
            view.header().resizeSection(column, width)
        BaseStyles.switch_theme("Light" if previous_theme == "Dark" else "Dark")
        page._toggle_view()
        page._toggle_view()
        page._populate(apps)
        qt_application.processEvents()
        assert [view.columnWidth(column) for column in range(4)] == expected
    finally:
        page.close()
        BaseStyles.switch_theme(previous_theme)


@pytest.mark.ui
def test_icon_selection_preserves_hidden_selected_apps(qt_application):
    """筛选隐藏的已选应用仍属于选择集，Ctrl 点选可见行不会清除它。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([
            ("Alpha", "com.example.alpha", "Enabled", "User"),
            ("Beta", "com.example.beta", "Enabled", "User"),
        ])
        page._toggle_view()
        page.resize(1000, 800)
        page.show()
        qt_application.processEvents()
        view = page.icon_list
        hidden = view.topLevelItem(0)
        visible = view.topLevelItem(1)
        hidden.setSelected(True)
        page.search_input.setText("Beta")
        qt_application.processEvents()
        assert hidden.isHidden() and hidden.isSelected()
        rect = view.visualRect(view.indexFromItem(visible, 1))
        assert view.viewport().rect().contains(rect)
        QTest.mouseClick(
            view.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier, rect.center(),
        )
        assert page.selected_packages == {"com.example.alpha", "com.example.beta"}
        assert hidden.isSelected() and visible.isSelected()
        assert all(
            page.model.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(2)
        )
    finally:
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("current_column", [0, 2, 3])
def test_icon_keyboard_search_uses_application_name_column(qt_application, current_column):
    """任意当前列的字母定位都按名称累积匹配，不受空图标列和包名影响。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([
            ("Alpha", "com.example.keep_alpha", "Enabled", "User"),
            ("Basil", "com.example.keep_basil", "Enabled", "User"),
            ("Beagle", "com.example.hidden", "Enabled", "User"),
            ("Beryl", "com.example.keep_beryl", "Enabled", "User"),
        ])
        page._toggle_view()
        page.resize(1000, 800)
        page.show()
        qt_application.processEvents()
        view = page.icon_list
        view.setCurrentItem(view.topLevelItem(0), current_column)
        view.setFocus()
        assert view.currentItem().text(0) == ""
        QTest.keyClick(view, Qt.Key.Key_B)
        assert view.currentItem().text(1) == "Basil"
        QTest.keyClick(view, Qt.Key.Key_E)
        assert view.currentItem().text(1) == "Beagle"
        assert page.selected_packages == {"com.example.hidden"}
    finally:
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_icon_selection_background_stays_inside_cell_after_horizontal_scroll(
    qt_application, theme,
):
    """首列几乎滚出视口时，选中底板不能越界给名称列重复叠色。"""
    previous_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme(theme)
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([("Alpha", "com.example.alpha", "Enabled", "User")])
        page._toggle_view()
        page.resize(520, 700)
        page.show()
        qt_application.processEvents()
        view = page.icon_list
        view.topLevelItem(0).setSelected(True)
        view.horizontalScrollBar().setValue(view.columnWidth(0) - 2)
        qt_application.processEvents()
        name_rect = view.visualRect(view.model().index(0, 1))
        assert name_rect.left() == 2
        image = view.viewport().grab().toImage()
        # 取文字上方、同一名称单元格的选中背景，避开图标和字符抗锯齿。
        y = name_rect.top() + 5
        assert image.pixelColor(name_rect.left(), y) == image.pixelColor(name_rect.left() + 16, y)
    finally:
        page.close()
        BaseStyles.switch_theme(previous_theme)


@pytest.mark.parametrize("column_widths", [[48, 160, 280, 100], [72, 320, 480, 140]])
def test_icon_rows_align_icon_and_text_on_one_line(qt_application, column_widths):
    """每个单元格只绘制自身内容，四列在不同行共享水平起点和垂直中线。"""
    page = AppManagerPage(device_ip="visual-demo")
    page._populate([
        ("一个较长的应用名称", "com.example.first", "Enabled", "User"),
        ("应用二", "com.example.second", "Disabled", "System"),
    ])
    icon_image = QImage(32, 32, QImage.Format.Format_ARGB32)
    icon_image.fill(QColor("#E600C8"))
    for row in range(2):
        page.icon_list.topLevelItem(row).setIcon(0, QIcon(QPixmap.fromImage(icon_image)))
    drawn_rows = []
    try:
        for column, width in enumerate(column_widths):
            page.icon_list.header().resizeSection(column, width)

        class TextPainter(QPainter):
            def drawText(self, rect, flags, text):
                drawn.append((rect, text))
                return super().drawText(rect, flags, text)

        for row in range(2):
            drawn = []
            image = QImage(sum(column_widths), 58, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = TextPainter(image)
            cell_rects = []
            try:
                for column in range(4):
                    option = QStyleOptionViewItem()
                    page.icon_list.initViewItemOption(option)
                    option.rect = QRect(
                        sum(column_widths[:column]), 0, column_widths[column], image.height(),
                    )
                    cell_rects.append(QRect(option.rect))
                    before = len(drawn)
                    page.icon_list.itemDelegate().paint(
                        painter, option, page.icon_list.model().index(row, column),
                    )
                    assert len(drawn) - before == (0 if column == 0 else 1)
            finally:
                painter.end()
            assert len(drawn) == 3
            assert {rect.center().y() for rect, _ in drawn} == {image.rect().center().y()}
            icon_pixels = [
                y for y in range(image.height())
                if image.pixelColor(cell_rects[0].center().x(), y) == QColor("#E600C8")
            ]
            assert (min(icon_pixels) + max(icon_pixels)) // 2 == image.rect().center().y()
            assert all(cell.contains(rect) for cell, (rect, _) in zip(cell_rects[1:], drawn))
            assert [
                rect.left() - cell.left() for cell, (rect, _) in zip(cell_rects[1:], drawn)
            ] == [12] * 3
            drawn_rows.append(drawn)
        assert [rect.left() for rect, _ in drawn_rows[0]] == [
            rect.left() for rect, _ in drawn_rows[1]
        ]
        assert drawn_rows[0][-1][1] == "已启用"
        assert drawn_rows[1][-1][1] == "已停用"
    finally:
        page.close()


@pytest.mark.parametrize("width,font_size", [(500, 12), (1000, 12), (720, 22)])
def test_icon_view_uses_full_width_rows_after_resize(qt_application, monkeypatch, width, font_size):
    """窄视口保留全部四列并支持横滚，窗口变宽不覆盖用户列宽或改变行高。"""
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda cls, role, size=None: QFont("Arial", size or font_size)),
    )
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([
            (f"示例应用 {row}", f"com.example.app{row}", "Enabled", "User")
            for row in range(8)
        ])
        page._toggle_view()
        page.resize(width, 900)
        page.show()
        view = page.icon_list
        column_widths = [64, 300, 700, 150]
        for column, column_width in enumerate(column_widths):
            view.header().resizeSection(column, column_width)
        qt_application.processEvents()
        first, second = [view.visualItemRect(view.topLevelItem(row)) for row in (0, 1)]
        assert second.top() >= first.bottom()
        assert first.left() == second.left()
        assert first.height() >= max(54, QFontMetrics(view.font()).height() + 20)
        assert all(not view.isColumnHidden(column) for column in range(4))
        scrollbar = view.horizontalScrollBar()
        before_maximum = scrollbar.maximum()
        assert before_maximum > 0
        scrollbar.setValue(before_maximum)
        qt_application.processEvents()
        status_rect = view.visualRect(view.model().index(0, 3))
        assert view.viewport().rect().contains(status_rect)
        page.resize(width + 160, 900)
        qt_application.processEvents()
        assert scrollbar.maximum() < before_maximum
        resized = view.visualItemRect(view.topLevelItem(0))
        assert resized.height() == first.height()
        assert [view.columnWidth(column) for column in range(4)] == column_widths
    finally:
        page.close()



def test_icon_rows_keep_full_names_for_search_and_accessible_details(qt_application):
    """省略仅发生在绘制，长名称尾部和晚到详情仍可搜索并供辅助技术读取。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        name = "这是一个长度超过十八字符的应用名称末尾关键字"
        package = "com.example.long_name"
        page._populate([(name, package, "Disabled", "System")])
        item = page.icon_list.topLevelItem(0)
        assert item.text(1) == name
        page.search_input.setText("末尾关键字")
        assert not item.isHidden()
        assert page.proxy.rowCount() == 1
        updated_name = name + "更新"
        page._on_detail(package, updated_name, "3.2.18", "")
        assert item.text(1) == updated_name
        description = item.data(0, Qt.ItemDataRole.AccessibleDescriptionRole)
        assert all(value in description for value in (package, "3.2.18", "已停用", "系统"))
        assert all(value in item.toolTip(1) for value in (updated_name, "已停用", "系统"))
        page.search_input.setText("晚到名称")
        assert item.isHidden() and page.proxy.rowCount() == 0
        page._on_detail(package, "晚到名称", "3.2.19", "")
        assert not item.isHidden() and page.proxy.rowCount() == 1
    finally:
        page.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_disabled_icon_rows_refresh_existing_foreground(qt_application, theme):
    """已有停用项即时跟随主题，切换不重建列表或丢失选择。"""
    previous = BaseStyles.current_theme()
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    page = AppManagerPage(device_ip="visual-demo")
    try:
        package = "com.example.disabled"
        page._populate([("停用应用", package, "Disabled", "System")])
        item = page.icon_list.topLevelItem(0)
        item.setSelected(True)
        BaseStyles.switch_theme(theme)
        qt_application.processEvents()
        assert page.icon_list.topLevelItem(0) is item
        assert item.foreground(1).color() == BaseStyles.get_color("TEXT_DISABLED")
        assert page.selected_packages == {package}
        # 检查实际文本绘制的笔色，不能只验证模型中缓存的 ForegroundRole。
        class TextPainter(QPainter):
            def drawText(self, *args):
                colors.append(self.pen().color())
                return super().drawText(*args)

        colors = []
        image = QImage(500, 140, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        option = QStyleOptionViewItem()
        page.icon_list.initViewItemOption(option)
        option.rect = image.rect()
        painter = TextPainter(image)
        try:
            page.icon_list.itemDelegate().paint(
                painter, option, page.icon_list.indexFromItem(item, 1),
            )
        finally:
            painter.end()
        assert colors[0] == BaseStyles.get_color("TEXT_DISABLED")
    finally:
        page.close()
        BaseStyles.switch_theme(previous)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_icon_row_selection_indicator_follows_accent(qt_application, theme):
    """强调色改变后已有选中行即时重绘，选择集合和条目身份保持不变。"""
    previous_theme = BaseStyles.current_theme()
    previous_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme(theme)
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page._populate([("示例应用", "com.example.app", "Enabled", "User")])
        item = page.icon_list.topLevelItem(0)
        item.setSelected(True)
        colors = []
        for accent in ("#0078D4", "#C239B3"):
            BaseStyles.set_accent_color(accent)
            qt_application.processEvents()
            image = QImage(500, 140, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            option = QStyleOptionViewItem()
            page.icon_list.initViewItemOption(option)
            option.rect = image.rect()
            option.state |= QStyle.StateFlag.State_Selected
            painter = QPainter(image)
            try:
                page.icon_list.itemDelegate().paint(
                    painter, option, page.icon_list.indexFromItem(item),
                )
            finally:
                painter.end()
            colors.append(image.pixelColor(5, image.height() // 2))
            assert page.icon_list.topLevelItem(0) is item
            assert page.selected_packages == {"com.example.app"}
        assert colors[0].alpha() == colors[1].alpha() == 255
        assert colors[0] != colors[1]
    finally:
        page.close()
        BaseStyles.set_accent_color(previous_accent)
        BaseStyles.switch_theme(previous_theme)


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
        # 普通布局留白透出工作区材质；下面的列表行仍需独立保持实色可读。
        assert surface.alpha() == 0
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
            page.icon_list.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)
            for row in range(page.icon_list.topLevelItemCount())
            if not page.icon_list.topLevelItem(row).isHidden()
        ]
        assert visible == ["com.example.system"]
        assert page.selected_packages == {"com.example.user"}
    finally:
        page.close()


def test_operation_feedback_keeps_list_space_and_forwards_records(qt_application, monkeypatch):
    """执行反馈交给任务中心，不创建或展开会挤压列表的本地记录区。"""
    records = []
    monkeypatch.setattr(
        "gui.dialogs.app_manager.report_feedback", lambda *a, **kw: records.append(a),
    )
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page.resize(720, 600)
        page.show()
        qt_application.processEvents()
        page.log("第一条操作记录")
        height = page.stack.height()
        assert not hasattr(page, "log_output")
        page.log("第二条操作记录")
        qt_application.processEvents()
        assert page.stack.height() == height
        assert [record[3] for record in records] == ["第一条操作记录", "第二条操作记录"]
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
            for index in range(view.topLevelItemCount()):
                rect = view.visualRect(view.model().index(index, 0))
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


def test_workspace_preparation_removes_duplicate_header_and_device_badge(qt_application):
    """嵌入页面由宿主页头呈现设备，筛选行只保留状态的辅助说明。"""
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
        assert not page.status_badge.isVisibleTo(page)
        assert page._search_control is page.search_input
        assert page.status_badge.text() in page.search_input.accessibleDescription()
        assert page.workspace_content_minimum_size().height() < before
        page.set_device_connected(False)
        assert page.status_badge.text() == "离线"
        assert not page.status_badge.isVisibleTo(page)
        assert "离线" in page.search_input.toolTip()
        assert "离线" in page.search_input.accessibleDescription()
    finally:
        page.close()


def test_workspace_filters_use_natural_widths_on_one_row_at_748(qt_application, monkeypatch):
    """扣除页面和面板留白后的 748px 筛选行仍为单行，固定控件不吸收多余宽度。"""
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda cls, role, size=None: QFont("Arial", size or 12)),
    )
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page.prepare_for_workspace()
        page.resize(812, 700)
        page.show()
        qt_application.processEvents()
        assert page._action_layout_available_width() == 748
        rows = {
            page._top_layout.getItemPosition(page._top_layout.indexOf(control))[0]
            for control in page._top_controls
        }
        assert rows == {0}
        assert abs(page.type_filter.width() - page.type_filter.sizeHint().width()) <= 2
        assert page.view_toggle.width() <= 40
        type_width = page.type_filter.width()
        search_width = page.search_input.width()
        page.resize(952, 700)
        qt_application.processEvents()
        assert page.type_filter.width() == type_width
        assert page.search_input.width() > search_width
        assert not page.status_badge.isVisibleTo(page)
    finally:
        page.close()


def test_standalone_manager_ready_badge_keeps_natural_width(qt_application):
    """独立页面仍呈现设备徽标，短状态不保留长状态的空白。"""
    page = AppManagerPage(device_ip="visual-demo")
    try:
        page.resize(952, 700)
        page.show()
        for selected in (False, True):
            page.set_device_selected(selected)
            qt_application.processEvents()
            assert page.status_badge.isVisibleTo(page)
            assert abs(page.status_badge.width() - page.status_badge.sizeHint().width()) <= 2
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
        for control in page._top_controls:
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
