"""用真实翻译和窗口几何验证检查器层次及单例阅读操作。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QAbstractButton, QLabel, QStyle, QStyleOptionFrame

from core.settings_manager import AppSettings
from gui.i18n import install_translators, tr
from gui.styles import BaseStyles
from tests.test_task_feedback import _result
from tests.test_task_feedback import task_feedback as task_feedback
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("language", ["zh_CN", "en_US"])
@pytest.mark.parametrize("size", [12, 22])
@pytest.mark.parametrize("width", [280, 390])
def test_completed_inspector_has_one_title_and_one_reachable_result_toolbar(
    task_feedback, qt_application, monkeypatch, language, size, width,
):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": size, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    try:
        coordinator, page, *_ = task_feedback()
        panel = coordinator.drawer
        surface = panel.parentWidget()
        surface.resize(width, 640)
        first = _result("current", state="succeeded")
        second = replace(first, request_id="other", spec=replace(first.spec, title="其他查询"))
        page.present_action_result(first)
        page.present_action_result(second)
        assert coordinator.open_request("current")
        panel.open_drawer(animated=False)
        reader = page.action_results
        controls = (reader.search, reader.copy_button, reader.export_button)
        wait_for_stable_geometry(qt_application, (panel, *controls, reader.output))
        labels = [label.text() for label in panel.findChildren(QLabel) if label.isVisibleTo(panel)]
        buttons = [button.accessibleName() or button.text() for button in
                   panel.findChildren(QAbstractButton) if button.isVisibleTo(panel)]
        assert tr("任务详情") not in labels and tr("最近") not in labels
        assert labels.count(tr(first.spec.title)) == 1
        assert not {tr("返回来源页面"), tr("在任务中心查看"), "其他查询"}.intersection(buttons)
        assert panel.title_label.mapTo(panel, QPoint()).y() < panel.scroll_area.y()
        assert panel.scroll_area.geometry().bottom() == panel.rect().bottom()
        assert panel.status_label.toolTip() == tr("本次会话 · 需要保留的正文请导出")
        assert reader.history.isHidden()
        for tool, caption in zip(controls[1:], ("复制完整结果", "导出结果")):
            assert not tool.icon().isNull() and not tool.text()
            # 图标资源存在仍可能绘在固定窄按钮以外；检查控件中央实际画出的字形。
            image = panel.grab().toImage()
            center = tool.mapTo(panel, tool.rect().center())
            cx = round(center.x() * image.devicePixelRatio())
            cy = round(center.y() * image.devicePixelRatio())
            radius = round(9 * image.devicePixelRatio())
            values = [image.pixelColor(x, y).lightness() for x in range(cx-radius, cx+radius)
                      for y in range(cy-radius, cy+radius)]
            assert max(values) - min(values) > 48
            assert tool.accessibleName() == tr(caption)
            assert tool.toolTip() == tool.accessibleDescription() and tool.toolTip()
            assert tool.focusPolicy() & Qt.FocusPolicy.TabFocus
            assert panel.rect().contains(tool.mapTo(panel, tool.rect().bottomRight()))
            assert tool.mapTo(panel, tool.rect().center()).y() == reader.search.mapTo(
                panel, reader.search.rect().center(),
            ).y()
        assert reader.search.mapTo(panel, reader.search.rect().bottomRight()).y() < (
            reader.output.mapTo(panel, QPoint()).y()
        )
        field = reader.search
        option = QStyleOptionFrame()
        field.initStyleOption(option)
        area = field.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, field)
        room = area.width() - field.textMargins().left() - field.textMargins().right() - 4
        assert room >= field.fontMetrics().horizontalAdvance(field.placeholderText())
        exported = QSignalSpy(reader.export_requested)
        reader.search.setFocus()
        assert reader.search.hasFocus()
        QTest.keyClick(reader.search, Qt.Key.Key_Tab)
        assert reader.copy_button.hasFocus()
        QTest.keyClick(reader.copy_button, Qt.Key.Key_Tab)
        assert reader.export_button.hasFocus()
        QTest.keyClick(reader.export_button, Qt.Key.Key_Space)
        assert exported.count() == 1
        assert exported.at(0) == ["current", first.items[0].detail]
        assert [item.request_id for item in reader.records_snapshot()] == ["current", "other"]
    finally:
        for translator in translators:
            qt_application.removeTranslator(translator)


def test_request_message_is_shown_once_and_target_change_restores_distinct_message(task_feedback):
    coordinator, page, *_ = task_feedback()
    sample = _result("error", state="failed")
    sample = replace(sample, message="请求收尾失败", items=(
        replace(sample.items[0], detail="请求收尾失败"),
        replace(sample.items[0], job_id="second", detail="另一个命令的完整错误"),
    ))
    page.present_action_result(sample)
    coordinator.open_request("error")
    reader = page.action_results
    assert reader.output.toPlainText() == sample.message
    assert reader.message_label.isHidden()
    reader.targets.setCurrentIndex(1)
    assert reader.output.toPlainText() == sample.items[1].detail
    assert reader.message_label.isVisibleTo(coordinator.drawer)
    assert reader.message_label.text() == sample.message


def test_archive_with_default_parameters_keeps_reuse_without_an_empty_json_panel(
    qt_application, tmp_path,
):
    from gui.run_library import RunLibraryController
    from gui.widgets.run_results import RunResultsWidget
    from services.run_library import RunLibrary, RunRecord

    library = RunLibraryController(RunLibrary(tmp_path / "runs.json"))
    reader = RunResultsWidget(library, detail_only=True)
    try:
        reader.set_hosted_full_results(True)
        record = RunRecord("archive", "monkey", "com.example.test", 1.0, 2.0, "succeeded", {}, ())
        reader.present_record(record)
        reader.show()
        assert reader.parameters_heading.isHidden() and reader.parameters_section.isHidden()
        assert reader.artifact_heading.isHidden() and reader.artifact_section.isHidden()
        assert reader.reuse_button.isVisible() and reader.reuse_button.isEnabled()
        reused = QSignalSpy(reader.reuse_requested)
        reader.reuse_button.click()
        assert reused.count() == 1
        assert reused.at(0)[0] == record
        reader.present_record(replace(record, parameters={"seed": 42}))
        assert reader.parameters_heading.isVisible() and reader.parameters_edit.isVisible()
    finally:
        reader.close()
        assert library.shutdown()


def test_long_command_hint_wraps_on_narrow_reader_and_retains_original_text(
    task_feedback, qt_application, monkeypatch,
):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": 22, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    coordinator, page, *_ = task_feedback()
    panel = coordinator.drawer
    panel.parentWidget().resize(280, 640)
    sample = _result(state="succeeded")
    command = "Shell [getprop ro.build.version.release😀_long_property_identifier]"
    page.present_action_result(replace(sample, message=command))
    coordinator.open_request("fixture")
    panel.open_drawer(animated=False)
    label = page.action_results.message_label
    wait_for_stable_geometry(qt_application, (panel, page.action_results, label))
    assert label.minimumSizeHint().width() <= page.action_results.width()
    assert label.width() <= page.action_results.width()
    assert label.toolTip() == command
    assert label.text().replace("\u200b", "") == command
    assert page.action_results.output.toPlainText() == sample.items[0].detail


def test_installing_hosted_mode_preserves_existing_reader_actions_and_request_message(
    qt_application,
):
    from gui.widgets.action_result_view import ActionResultView

    reader = ActionResultView(inline=True)
    sample = replace(_result(state="failed"), message="请求级说明")
    reader.present(sample)
    reader.output.selectAll()
    reader.search.setText("合成")
    buttons = (reader.copy_button, reader.export_button)
    original_policies = [button.focusPolicy() for button in buttons]
    try:
        reader.set_hosted_full_results(True)
        assert reader.message_label.text() == sample.message
        assert reader.output.textCursor().selectedText() == sample.items[0].detail
        assert reader.search.text() == "合成"
        reader.set_hosted_full_results(False)
        assert buttons == (reader.copy_button, reader.export_button)
        assert [b.text() for b in buttons] == [tr("复制完整结果"), tr("导出结果")]
        assert all(b.icon().isNull() for b in buttons)
        assert [button.focusPolicy() for button in buttons] == original_policies
        assert reader.search.placeholderText() == tr("查找结果，按 Enter 查找下一处")
        assert reader.message_label.text() == sample.message
    finally:
        reader.close()
        reader.deleteLater()


def test_request_title_does_not_repeat_as_an_independent_message(task_feedback):
    coordinator, page, *_ = task_feedback()
    sample = _result(state="succeeded")
    page.present_action_result(replace(sample, message=tr(sample.spec.title)))
    assert coordinator.open_request("fixture")
    assert coordinator.drawer.title_label.accessibleName() == tr(sample.spec.title)
    assert page.action_results.message_label.isHidden()
    assert page.action_results.output.toPlainText() == sample.items[0].detail


@pytest.mark.parametrize("language,caption", [("zh_CN", "成功"), ("en_US", "部分成功")])
@pytest.mark.parametrize("size", ["Auto", 12, 13, 22])
@pytest.mark.parametrize("width", [280, 390])
def test_status_badge_reserves_readable_width_before_source(
    task_feedback, qt_application, monkeypatch, language, caption, size, width,
):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": size, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    try:
        coordinator, page, *_ = task_feedback()
        panel = coordinator.drawer
        panel.parentWidget().resize(width, 640)
        sample = _result(state="succeeded")
        page.present_action_result(sample)
        assert coordinator.open_request(sample.request_id)
        row = page.detail_row("action:fixture")
        panel.present(replace(row, state=tr(caption)), source_label=tr("系统工具"))
        panel.open_drawer(animated=False)
        status, source = panel.status_label, panel.source_label
        wait_for_stable_geometry(qt_application, (panel, status, source))
        margins = status.contentsMargins()
        natural = (status.fontMetrics().horizontalAdvance(status.text())
                   + margins.left() + margins.right())
        room = panel.meta_host.contentsRect().width()
        assert status.width() >= min(natural, room)
        # 用同一 QLabel 的宽幅行高度量真实中文回退字体；文本过宽时按整行换行。
        reference_width = max(2048, natural * 2) if natural <= room else room
        expected_height = status.heightForWidth(reference_width)
        assert expected_height > 0 and status.heightForWidth(status.width()) == expected_height
        assert status.height() >= expected_height
        assert panel.meta_host.rect().contains(status.geometry())
        assert panel.meta_host.rect().contains(source.geometry())
        assert not status.geometry().intersects(source.geometry())
        assert source.width() >= source.fontMetrics().horizontalAdvance(source.text())
        if natural > room:
            assert source.y() > status.geometry().bottom()
    finally:
        for translator in translators:
            qt_application.removeTranslator(translator)


def test_closing_and_reversing_repaints_the_exposed_background_strip(qt_application):
    from PySide6.QtGui import QColor, QPalette, QRegion
    from PySide6.QtWidgets import QWidget

    from gui.widgets.task_detail_drawer import TaskDetailDrawer
    from gui.widgets.task_table import TaskRowData
    from tests.ui_geometry_helpers import wait_until

    class Background(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.painted = QRegion()
            palette = self.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#85118d"))
            self.setPalette(palette)
            self.setAutoFillBackground(True)

        def paintEvent(self, event):  # noqa: N802
            self.painted |= event.region()
            super().paintEvent(event)

    host = QWidget()
    host.resize(760, 500)
    background = Background(host)
    background.setGeometry(host.rect())
    panel = TaskDetailDrawer(host)
    panel.present(TaskRowData("fixture", "绘制检查", "系统", "设备", "成功", "success", "", ""))
    host.show()
    try:
        wait_until(qt_application, lambda: not background.painted.isEmpty())
        reference = host.grab().toImage()
        panel.open_drawer(animated=False)
        wait_for_stable_geometry(qt_application, (host, panel))
        opened_left = panel.x()
        for opening, position in ((False, 90), (True, 30)):
            background.painted = QRegion()
            if opening:
                panel.open_drawer()
            else:
                panel.close_drawer()
            panel.animation.pause()
            panel.animation.setCurrentTime(position)
            exposed = background.rect().adjusted(opened_left, 2, panel.x() - host.width(), -2)
            assert exposed.isValid()
            if not opening:
                # 先等待下层真实 Paint，之后的合成取样才不会用 grab 主动绘制替代更新。
                wait_until(
                    qt_application,
                    lambda: QRegion(exposed).subtracted(background.painted).isEmpty(),
                )
                closing_left = panel.x()
            else:
                assert opened_left < panel.x() < closing_left
            painted = host.grab().toImage()
            scale = painted.devicePixelRatio()
            crop = (round(exposed.x() * scale), round(exposed.y() * scale),
                    round(exposed.width() * scale), round(exposed.height() * scale))
            assert painted.copy(*crop) == reference.copy(*crop)
            assert painted.pixelColor(round((panel.x() + 4) * scale), round(8 * scale)) == (
                QColor(BaseStyles.color("CONTENT_BG"))
            )
    finally:
        panel.shutdown()
        host.close()
        host.deleteLater()


def test_reopen_after_hidden_layout_keeps_title_and_viewport_readable(qt_application):
    from PySide6.QtCore import QAbstractAnimation
    from PySide6.QtWidgets import QWidget

    from gui.widgets.task_detail_drawer import TaskDetailDrawer
    from gui.widgets.task_table import TaskRowData
    from tests.ui_geometry_helpers import wait_until

    window = QWidget()
    window.resize(812, 723)
    surface = QWidget(window)
    surface.setGeometry(48, 40, 764, 683)
    panel = TaskDetailDrawer(surface)
    row = TaskRowData("fixture", "检查布局", "系统", "设备", "成功", "success", "", "")

    def assert_readable():
        title = panel.title_label
        assert title.width() >= title.fontMetrics().horizontalAdvance(title.text()) > 0
        assert panel.rect().contains(title.mapTo(panel, title.rect().center()))
        assert panel.scroll_area.viewport().width() >= panel.width() - 2
        assert panel.body.width() >= panel.width() - 2

    def check_visible_frames():
        panel.animation.pause()
        for time_ms in (60, 150):
            panel.animation.setCurrentTime(time_ms)
            qt_application.processEvents()
            assert surface.width() - panel.width() < panel.x() < surface.width()
            assert_readable()
        panel.animation.resume()

    window.show()
    try:
        if qt_application.platformName() == "cocoa":
            import objc
            from AppKit import NSEdgeInsetsMake

            # 普通测试窗口独立模拟标题栏安全区，其他平台也执行同一开关及几何断言。
            view = objc.objc_object(c_void_p=int(window.winId()))
            view.setAdditionalSafeAreaInsets_(NSEdgeInsetsMake(12, 0, 0, 0))
            wait_until(qt_application, lambda: window.contentsMargins().top() >= 12)
        for _ in range(2):
            panel.present(row)
            # 隐藏态刷新可重新激活布局，此时侧栏仍完全在宿主右边界以外。
            panel.layout().invalidate()
            panel.layout().activate()
            panel.open_drawer()
            check_visible_frames()
            wait_until(qt_application, lambda: (
                panel.animation.state() == QAbstractAnimation.State.Stopped
            ))
            assert_readable()
            panel.close_drawer()
            check_visible_frames()
            wait_until(qt_application, lambda: not panel.isVisible())
    finally:
        panel.shutdown()
        window.close()
        window.deleteLater()
