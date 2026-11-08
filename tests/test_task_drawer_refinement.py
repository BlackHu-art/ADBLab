"""验证任务抽屉外侧关闭的完整手势与紧凑阅读呈现。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QPushButton, QWidget, QWidgetAction
from shiboken6 import delete, isValid

from core.settings_manager import AppSettings
from gui.pages.tasks_page import TaskCenterPage
from gui.session_tasks import SessionTaskSnapshot
from gui.styles import BaseStyles
from gui.task_feedback import TaskFeedbackCoordinator
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from services.tasks.operations import OperationManager

pytestmark = pytest.mark.ui


def result(request="fixture", *, state="succeeded", targets=("synthetic",), items=None):
    return ActionResult(
        request, ActionSpec("shell", "system", "Shell 命令"), targets, 1.0,
        state=state, message="Shell [echo]：命令提示", finished_at=2.0,
        items=items if items is not None else (
            ActionItem("job", targets[0] if targets else None, "Shell 命令", state, "完整输出"),
        ),
    )


@pytest.fixture
def feedback(qt_application):
    window = QWidget()
    window.resize(1000, 740)
    surface = QWidget(window)
    surface.setGeometry(180, 40, 820, 700)
    outside = QPushButton("页面操作", surface)
    outside.setGeometry(20, 500, 150, 50)
    navigation = QWidget(window)
    navigation.setGeometry(0, 40, 180, 700)
    nav = QPushButton("导航入口", navigation)
    nav.setGeometry(10, 300, 150, 50)
    chrome = QPushButton("窗口管理", window)
    chrome.setGeometry(0, 0, 180, 35)
    page = TaskCenterPage(OperationManager(), external_details=True, parent=surface)
    page.hide()
    coordinator = TaskFeedbackCoordinator(
        page, surface, navigation_parent=navigation, show_task_center=lambda: None,
        open_source=lambda _source: None, is_task_center=lambda: False, parent=window,
    )
    window.show()
    page.hide()
    page.present_action_result(result())
    assert coordinator.open_request("fixture")
    coordinator.drawer.open_drawer(animated=False)
    qt_application.processEvents()
    state = SimpleNamespace(window=window, surface=surface, outside=outside, nav=nav,
                            chrome=chrome, coordinator=coordinator, page=page,
                            drawer=coordinator.drawer)
    yield state
    if isValid(window):
        coordinator.shutdown()
        page.shutdown()
        window.close()
        window.deleteLater()


def hit(button):
    point = button.mapToGlobal(button.rect().center())
    target = QApplication.widgetAt(point)
    assert target is button
    return target, button.mapFromGlobal(point)


@pytest.fixture
def metadata_feedback(qt_application, monkeypatch, size, request):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": size, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    return request.getfixturevalue("feedback")


@pytest.mark.parametrize("which", ["outside", "nav"])
def test_first_outside_click_only_dismisses_and_next_new_click_works(feedback, which):
    button = getattr(feedback, which)
    target, point = hit(button)
    pressed = QSignalSpy(button.pressed)
    clicked = QSignalSpy(button.clicked)
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=point)
    assert not feedback.drawer.opened
    assert pressed.count() == 0
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=point)
    assert clicked.count() == 0
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=point)
    assert pressed.count() == 1
    assert clicked.count() == 1


@pytest.mark.parametrize("boundary", ["hidden", "resize", "reopen"])
def test_dismissal_tail_does_not_reach_background_after_presentation_changes(feedback, boundary):
    button, point = hit(feedback.outside)
    events = []
    class Probe(QObject):
        def eventFilter(self, watched, event):  # noqa: N802
            if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
                events.append(event.type())
            return False

    probe = Probe(button)
    button.installEventFilter(probe)
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
    assert not feedback.drawer.opened
    feedback.drawer.animation.stop()
    feedback.drawer._finish()
    if boundary == "resize":
        feedback.window.resize(900, 680)
    elif boundary == "reopen":
        feedback.page.present_action_result(result("other"))
        feedback.coordinator.open_request("other")
        feedback.drawer.open_drawer(animated=False)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(button, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)
    assert events == []
    if boundary == "reopen":
        assert feedback.drawer.opened
        assert feedback.drawer.selected_key == "action:other"


def test_inside_drag_owned_popup_modal_and_window_chrome_do_not_dismiss(feedback, qt_application):
    # 默认窗口位置可能跨越多屏间隙，先留出同屏外侧空间，避免平台把菜单挤回抽屉内。
    available = feedback.window.screen().availableGeometry()
    feedback.window.move(available.topLeft() + QPoint(20, 20))
    qt_application.processEvents()
    drawer = feedback.drawer
    QTest.mousePress(drawer.title_label, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(feedback.outside, Qt.MouseButton.LeftButton)
    assert drawer.opened
    menu = QMenu(drawer.title_label)
    action = QWidgetAction(menu)
    menu_button = QPushButton("弹出菜单操作")
    action.setDefaultWidget(menu_button)
    menu.addAction(action)
    triggered = QSignalSpy(menu_button.clicked)
    popup_position = drawer.mapToGlobal(QPoint(-180, 100))
    assert available.contains(popup_position)
    menu.popup(popup_position)
    qt_application.processEvents()
    assert not drawer.rect().contains(drawer.mapFromGlobal(
        menu_button.mapToGlobal(menu_button.rect().center()),
    ))
    QTest.mouseClick(menu_button, Qt.MouseButton.LeftButton)
    assert drawer.opened
    assert triggered.count() == 1
    menu.close()
    modal = QDialog(feedback.window)
    modal.setModal(True)
    modal.show()
    qt_application.processEvents()
    QTest.mouseClick(modal, Qt.MouseButton.LeftButton)
    assert drawer.opened
    modal.close()
    QTest.mouseClick(feedback.chrome, Qt.MouseButton.LeftButton)
    assert drawer.opened


def test_foreign_window_and_wheel_do_not_dismiss(feedback, qt_application):
    point = feedback.outside.rect().center()
    QApplication.sendEvent(feedback.outside, QWheelEvent(
        point, feedback.outside.mapToGlobal(point), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))
    QTest.keyClick(feedback.outside, Qt.Key.Key_Tab)
    assert feedback.drawer.opened
    other = QPushButton("其他窗口")
    other.show()
    qt_application.processEvents()
    try:
        QTest.mouseClick(other, Qt.MouseButton.LeftButton)
        assert feedback.drawer.opened
    finally:
        other.close()


def test_pending_tail_is_cleared_on_host_hide_and_shutdown(feedback, qt_application):
    button, point = hit(feedback.outside)
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
    feedback.window.hide()
    feedback.window.show()
    qt_application.processEvents()
    released = []
    original = button.mouseReleaseEvent

    def record(event):
        released.append(event.type())
        original(event)

    button.mouseReleaseEvent = record
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)
    assert released == [QEvent.Type.MouseButtonRelease]
    feedback.coordinator.shutdown()
    clicked = QSignalSpy(button.clicked)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=point)
    assert clicked.count() == 1


@pytest.mark.parametrize("boundary", ["window", "surface", "minimize", "destroy"])
def test_listener_and_bounded_timer_are_released_with_host(feedback, qt_application, boundary):
    button, point = hit(feedback.outside)
    observer = feedback.coordinator._outside
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
    assert observer._installed
    assert observer._double_timer.isActive()
    if boundary == "destroy":
        delete(feedback.window)
        assert not isValid(observer)
        return
    if boundary == "window":
        feedback.window.hide()
    elif boundary == "surface":
        feedback.surface.hide()
    else:
        feedback.window.showMinimized()
    qt_application.processEvents()
    assert not observer._installed
    assert not observer._double_timer.isActive()
    assert observer._pressed is None


def test_long_hold_keeps_release_protected_after_double_click_qualification_expires(feedback):
    button, point = hit(feedback.outside)
    released = []

    class Probe(QObject):
        def eventFilter(self, watched, event):  # noqa: N802
            if event.type() == QEvent.Type.MouseButtonRelease:
                released.append(event.type())
            return False

    probe = Probe(button)
    button.installEventFilter(probe)
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
    QTest.qWait(QApplication.styleHints().mouseDoubleClickInterval() + 20)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)
    assert released == []
    clicked = QSignalSpy(button.clicked)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=point)
    assert clicked.count() == 1


def test_release_in_another_window_finishes_observation_without_stealing_its_input(feedback):
    button, point = hit(feedback.outside)
    other = QPushButton("另一个窗口")
    other.show()
    try:
        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(other, Qt.MouseButton.LeftButton)
        QTest.qWait(QApplication.styleHints().mouseDoubleClickInterval() + 20)
        assert not feedback.coordinator._outside._installed
        clicked = QSignalSpy(other.clicked)
        QTest.mouseClick(other, Qt.MouseButton.LeftButton)
        assert clicked.count() == 1
    finally:
        other.close()


@pytest.mark.parametrize("long_hold", [False, True])
def test_outside_right_click_dismissal_cannot_open_a_background_context_menu(feedback, long_hold):
    button, point = hit(feedback.outside)
    contexts = []
    button.contextMenuEvent = lambda event: contexts.append(event.reason())
    QTest.mousePress(button, Qt.MouseButton.RightButton, pos=point)
    if long_hold:
        QTest.qWait(QApplication.styleHints().mouseDoubleClickInterval() + 20)
    QTest.mouseRelease(button, Qt.MouseButton.RightButton, pos=point)
    QApplication.sendEvent(button, QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, button.mapToGlobal(point),
    ))
    assert contexts == []


@pytest.mark.parametrize("difference", ["distance", "source"])
def test_unrelated_double_click_is_not_swallowed(feedback, difference):
    button = feedback.outside
    point = QPoint(10, 10)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=point)
    pressed = QSignalSpy(button.pressed)
    if difference == "distance":
        point = QPoint(120, 10)
        QTest.mouseDClick(button, Qt.MouseButton.LeftButton, pos=point)
    else:
        QApplication.sendEvent(button, QMouseEvent(
            QEvent.Type.MouseButtonDblClick, point, point, button.mapToGlobal(point),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier, Qt.MouseEventSource.MouseEventSynthesizedByApplication,
        ))
    assert pressed.count() == 1
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)


def test_hosted_single_success_hides_duplicate_target_summary_but_preserves_message(feedback):
    page = feedback.page
    assert page.device_summary.isHidden()
    assert page.action_results.targets.isHidden()
    assert page.action_results.message_label.text() == "Shell [echo]：命令提示"
    assert page.action_results._detail == "完整输出"
    assert page.action_results.output.isVisibleTo(feedback.drawer)
    assert page.action_results.output.toPlainText() == "完整输出"
    assert page.action_results.detail_toggle.isHidden()
    assert page.action_results.history.isHidden()


def test_task_list_selection_keeps_original_keys_and_same_inspector(feedback):
    page = feedback.page
    page.present_action_result(replace(result("second"), started_at=3.0))
    feedback.coordinator.open_request("fixture")
    feedback.drawer.close_drawer(animated=False)
    page.show()
    reader = page.action_results
    keys = tuple(row.key for row in page.recent_rows())
    assert keys == ("action:second", "action:fixture")
    page.table.rows["action:second"].title.click()
    assert page.selected_key == feedback.drawer.selected_key == "action:second"
    assert page.action_results is reader
    assert keys == tuple(row.key for row in page.recent_rows())


@pytest.mark.parametrize("variant", [
    "partial", "failed", "cancelled", "two-items", "wrong-target", "two-targets",
])
def test_compact_reader_keeps_nontrivial_result_status(feedback, variant):
    sample = result("complex")
    if variant in ("partial", "failed", "cancelled"):
        sample = replace(sample, state=variant)
    elif variant == "two-items":
        sample = replace(sample, items=sample.items + (
            replace(sample.items[0], job_id="second"),
        ))
    elif variant == "wrong-target":
        sample = replace(sample, items=(replace(sample.items[0], target="other"),))
    else:
        sample = replace(sample, targets=("synthetic", "second"))
    feedback.page.present_action_result(sample)
    feedback.coordinator.open_request("complex")
    reader = feedback.page.action_results
    assert reader.targets.isHidden() == (len(sample.items) < 2)
    if variant == "two-items":
        assert reader.targets.itemText(0) != reader.targets.itemText(1)
        assert [reader.targets.itemData(i) for i in range(2)] == ["job", "second"]
    else:
        assert not feedback.page.device_summary.isHidden()
        assert "已完成" in feedback.page.device_summary.text()
        if variant == "two-targets":
            assert "设备 1" in feedback.page.device_summary.text()


def test_single_success_compact_mode_keeps_standalone_and_local_result_truth(feedback):
    from gui.widgets.action_result_view import ActionResultView

    standalone = ActionResultView()
    standalone.present(result())
    assert not standalone.targets.isHidden()
    standalone.close()
    feedback.page.present_action_result(result("local", targets=()))
    feedback.coordinator.open_request("local")
    assert feedback.page.action_results.targets.isHidden()
    assert feedback.drawer.target_label.isHidden()
    assert feedback.page.action_results._detail == "完整输出"


@pytest.mark.parametrize("detail", ["", "完整会话内容请返回来源页面查看。", "完整会话正文"])
def test_hosted_session_keeps_one_target_and_one_source_hint(feedback, detail):
    snapshot = SessionTaskSnapshot(
        "session-owner", "revision", "logcat", "running", True, True,
        ("合成设备",), detail=detail,
    )
    feedback.page.set_session_snapshots((snapshot,))
    feedback.coordinator.open_entry("session:session-owner")
    assert feedback.drawer.target_label.text() == "合成设备"
    assert feedback.page.device_summary.isHidden()
    assert not feedback.page.detail_meta.isHidden()
    assert feedback.page.operation_output.isHidden() == (not detail or detail == (
        "完整会话内容请返回来源页面查看。"
    ))
    snapshot = replace(snapshot, state="stopping", stop_enabled=False)
    feedback.page.set_session_snapshots((snapshot,))
    button = feedback.drawer.cancel_button
    assert button.text() == button.toolTip() == button.accessibleDescription() == "正在停止"


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("size", [12, 22])
@pytest.mark.parametrize("width", [280, 390])
def test_long_task_title_and_close_remain_reachable(
    feedback, qt_application, monkeypatch, theme, size, width,
):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": size, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    title = "完整的很长同名任务标题" * 5
    for index in range(3):
        sample = replace(result(f"long-{index}"), started_at=3.0 + index,
                         spec=replace(result().spec, title=title),
                         target_labels=(f"合成设备{index}",))
        feedback.page.present_action_result(sample)
    feedback.coordinator.open_request("long-1")
    panel = feedback.drawer
    feedback.surface.resize(width, 600)
    panel.open_drawer(animated=False)
    qt_application.processEvents()
    assert panel.width() == width
    assert panel.scroll_area.horizontalScrollBar().maximum() == 0
    assert panel.title_label.font().pointSizeF() > panel.source_label.font().pointSizeF()
    assert panel.title_label.text() != title
    assert panel.title_label.toolTip() == panel.title_label.accessibleName() == title
    assert panel.target_label.text() == "合成设备1"
    button = panel.close_button
    assert panel.rect().contains(button.mapTo(panel, button.rect().topLeft()))
    assert panel.rect().contains(button.mapTo(panel, button.rect().bottomRight()))
    assert button.height() >= button.fontMetrics().height() + 8
    assert panel.title_label.geometry().right() < button.geometry().left()
    assert button.focusPolicy() != Qt.FocusPolicy.NoFocus


@pytest.mark.parametrize("first", [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton])
@pytest.mark.parametrize("release_original_first", [False, True])
def test_outside_chord_cannot_activate_home_card_until_every_button_is_released(
    feedback, qt_application, first, release_original_first,
):
    from qfluentwidgets import FluentIcon

    from gui.pages.home import ActionCard

    activated = []
    contexts = []
    card = ActionCard(FluentIcon.HOME, "首页快捷入口", "组合手势验证",
                      lambda: activated.append("home"), feedback.surface)
    card.contextMenuEvent = lambda event: contexts.append(event.reason())
    card.setGeometry(20, 350, 290, 110)
    card.show()
    qt_application.processEvents()
    point = card.mapTo(feedback.window, card.rect().center())
    assert QApplication.widgetAt(card.mapToGlobal(card.rect().center())) is not None
    window = feedback.window.windowHandle()
    assert window is not None
    second = (Qt.MouseButton.RightButton if first == Qt.MouseButton.LeftButton
              else Qt.MouseButton.LeftButton)
    QTest.mousePress(window, first, pos=point)
    assert not feedback.drawer.opened
    QTest.mousePress(window, second, pos=point)
    releases = (first, second) if release_original_first else (second, first)
    for button in releases:
        QTest.mouseRelease(window, button, pos=point)
        if button == Qt.MouseButton.RightButton:
            additional = button != releases[-1]
            if additional:
                QTest.mousePress(window, Qt.MouseButton.MiddleButton, pos=point)
            local = card.rect().center()
            QApplication.sendEvent(card, QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, local, card.mapToGlobal(local),
            ))
            if additional:
                QTest.mouseRelease(window, Qt.MouseButton.MiddleButton, pos=point)
    assert activated == []
    assert contexts == []
    local = card.rect().center()
    QApplication.sendEvent(card, QContextMenuEvent(
        QContextMenuEvent.Reason.Keyboard, local, card.mapToGlobal(local),
    ))
    assert contexts == [QContextMenuEvent.Reason.Keyboard]
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=point)
    assert activated == ["home"]


def test_target_names_only_success_keeps_its_supported_visible_device_name(feedback):
    sample = replace(result("legacy-name"), target_names=("Synthetic Model A",))
    feedback.page.present_action_result(sample)
    feedback.coordinator.open_request(sample.request_id)
    selector = feedback.page.action_results.targets
    header = feedback.drawer.target_label
    visible = [label.text() for label in (header,) if label.isVisibleTo(feedback.drawer)]
    if selector.isVisibleTo(feedback.drawer):
        visible.append(selector.currentText())
    assert any("Synthetic Model A" in text for text in visible)


@pytest.mark.parametrize("kind", ["foreign", "popup", "modal"])
def test_chord_in_another_window_keeps_its_input_and_protects_original_home_release(
    feedback, qt_application, kind,
):
    from qfluentwidgets import FluentIcon

    from gui.pages.home import ActionCard

    activated = []
    card = ActionCard(FluentIcon.HOME, "首页入口", "跨窗组合手势验证",
                      lambda: activated.append("home"), feedback.surface)
    card.setGeometry(20, 350, 290, 110)
    card.show()
    qt_application.processEvents()
    point = card.rect().center()
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=point)
    other = QDialog(feedback.window) if kind == "modal" else QWidget()
    if kind == "modal":
        other.setModal(True)
    elif kind == "popup":
        other.setParent(feedback.drawer.title_label)
        other.setWindowFlags(Qt.WindowType.Popup)
    target = QWidget(other)
    target.setGeometry(0, 0, 100, 80)
    other.resize(100, 80)
    received = []

    class Probe(QObject):
        def eventFilter(self, watched, event):  # noqa: N802
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                received.append((event.type(), event.button()))
            return False

    probe = Probe(target)
    target.installEventFilter(probe)
    other.show()
    qt_application.processEvents()
    try:
        local = QPoint(30, 30)
        for event_type, buttons in (
            (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton),
            (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton),
        ):
            QApplication.sendEvent(target, QMouseEvent(
                event_type, local, target.mapToGlobal(local), Qt.MouseButton.RightButton,
                buttons, Qt.KeyboardModifier.NoModifier,
            ))
        assert received == [(QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton),
                            (QEvent.Type.MouseButtonRelease, Qt.MouseButton.RightButton)]
    finally:
        other.close()
        qt_application.processEvents()
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=point)
    assert activated == []
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=point)
    assert activated == ["home"]


@pytest.mark.parametrize("variant", ["preferred-label", "local", "multiple"])
def test_name_compatibility_preserves_preferred_labels_local_and_multiple_targets(
    feedback, variant,
):
    sample = replace(result(variant), target_names=("Legacy Model",), target_labels=("首选标签",))
    if variant == "local":
        sample = replace(result(variant, targets=()), target_names=("Legacy Model",))
    elif variant == "multiple":
        sample = replace(result(variant, targets=("one", "two")),
                         target_names=("Legacy One", "Legacy Two"))
    feedback.page.present_action_result(sample)
    feedback.coordinator.open_request(sample.request_id)
    selector = feedback.page.action_results.targets
    if variant == "multiple":
        assert selector.isHidden()
        assert "Legacy One" in feedback.drawer.target_label.text()
        assert "Legacy Two" in feedback.drawer.target_label.text()
        assert "2 台目标设备" in feedback.drawer.target_label.text()
        assert "Legacy One" in feedback.page.device_summary.text()
    else:
        assert selector.isHidden()
        if variant == "preferred-label":
            assert feedback.drawer.target_label.text() == "首选标签"


@pytest.mark.parametrize("size", [12, 22])
@pytest.mark.parametrize("width", [280, 390])
@pytest.mark.parametrize("target", [
    "设备 1 · google sdk_gphone64_arm64", "设备 1 · sdk_gphone64_arm64",
])
def test_chinese_source_keeps_its_readable_width_beside_long_safe_target(
    metadata_feedback, qt_application, size, width, target,
):
    feedback = metadata_feedback
    sample = replace(result("long-target"), target_labels=(target,))
    feedback.page.present_action_result(sample)
    feedback.coordinator.open_request(sample.request_id)
    if width < 390:
        feedback.surface.resize(width, 600)
    feedback.drawer.open_drawer(animated=False)
    qt_application.processEvents()
    source = feedback.drawer.source_label
    assert source.text() == "系统工具"
    natural_width = source.fontMetrics().horizontalAdvance(source.text())
    assert source.width() >= natural_width
    single_line_height = source.heightForWidth(max(1, natural_width * 2))
    assert single_line_height > 0
    assert source.heightForWidth(source.width()) == single_line_height
    assert source.height() >= single_line_height
    assert feedback.drawer.scroll_area.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("variation", [
    "exact", "different-output", "extra-guidance", "failed", "wrong-target", "multiline-command",
])
def test_shell_preview_suppresses_only_verified_output_duplicate(feedback, variation):
    output = "x" * 220 + "end"
    command = "getprop ro.build.version.release"
    sample = result("shell-evidence")
    item = replace(sample.items[0], detail=output)
    header = f"Shell [设备 1] `{command}`:"
    if variation == "wrong-target":
        header = header.replace("设备 1", "设备 2")
    elif variation == "multiline-command":
        header = header.replace("getprop ", "echo a\ngetprop ")
    message = header + "\n" + output
    if variation == "different-output":
        message += "!"
    elif variation == "extra-guidance":
        message += "\n额外说明"
    elif variation == "failed":
        item = replace(item, state="failed")
    sample = replace(sample, spec=replace(sample.spec, key="run_shell_command"), items=(item,),
                     message=message, state=item.state)
    feedback.page.present_action_result(sample)
    feedback.coordinator.open_request(sample.request_id)
    reader = feedback.page.action_results
    label = reader.message_label
    assert not label.isHidden()
    assert label.toolTip() == label.accessibleDescription() == message
    assert reader.output.toPlainText() == output
    visible = label.text().replace("\u200b", "")
    assert command in visible or variation == "multiline-command"
    assert ("xxxxxxxx" in visible) == (variation != "exact")


def test_hosted_zero_jobs_and_real_device_named_local(feedback):
    sample = replace(result("no-jobs", state="running", items=()), target_labels=("本机",))
    feedback.page.present_action_result(sample)
    feedback.coordinator.open_request(sample.request_id)
    assert feedback.page.action_results.targets.isHidden()
    assert feedback.drawer.target_label.isVisibleTo(feedback.drawer)
    assert feedback.drawer.target_label.text() == "本机"
