"""验证 Monkey 的真实鼠标交互不会滚动跳焦，方案栏只占内容所需高度。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest

from tests.test_monkey_alignment import monkey_page as monkey_page
from tests.test_monkey_preparation import _success
from tests.test_responsive_panels import _resize_feature_viewport
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)

pytestmark = pytest.mark.ui


def _settle(app, owner, apps, scroll):
    """只推进事件和布局，不调整视口、焦点或滚动位置来掩盖交互跳动。"""
    wait_for_stable_geometry(app, (
        scroll.widget(), apps.monkey_package_card, apps.monkey_prepare_actions,
        apps.monkey_preset_bar, apps.monkey_parameters_card,
    ))
    wait_until(app, lambda: owner._responsive_coordinator.diagnostics.stable)
    wait_for_stable_geometry(app, (scroll.widget(), apps.monkey_prepare_actions))


def _assert_compact_preset_row(apps):
    """按真实标题是否换行计算必要高度，不把父布局分配的多余空间当成内容。"""
    preset = apps.monkey_preset_bar
    heading = apps.monkey_parameters_heading
    row = preset.parentWidget()
    required_height = preset.heightForWidth(preset.width())
    assert preset.height() == required_height
    if row.isAncestorOf(heading):
        heading_height = heading.heightForWidth(heading.width())
        if heading_height < 0:
            heading_height = heading.sizeHint().height()
        title_rect = mapped_rect(heading, row)
        preset_rect = mapped_rect(preset, row)
        if title_rect.bottom() < preset_rect.top():
            required_height += heading_height + row.layout().spacing()
        else:
            required_height = max(required_height, heading_height)
    margins = row.layout().contentsMargins()
    assert row.height() == required_height + margins.top() + margins.bottom()
    return row


@pytest.mark.parametrize("width,font_size,partial_scroll,terminal", [
    (900, 12, False, "success"),
    (900, 12, True, "cancel"),
    (420, 12, True, "success"),
    (420, 22, True, "cancel"),
    pytest.param(900, 12, True, "failure", id="failure-wide"),
    pytest.param(420, 22, True, "failure", id="failure-narrow-large-font"),
])
def test_mouse_package_query_keeps_viewport_and_focus_at_its_action(
    qt_application, monkey_page, width, font_size, partial_scroll, terminal,
):
    """原地获取、取消与完成始终留在包信息操作区，不经过下方参数或诊断按钮。"""
    owner, apps, scroll, content = monkey_page(width, font_size)
    get_button = apps.monkey_get_package_btn
    cancel_button = apps.monkey_cancel_prepare_btn
    actual_window = get_button.window()
    actual_window.activateWindow()
    wait_until(qt_application, lambda: qt_application.activeWindow() is actual_window)
    vertical = scroll.verticalScrollBar()
    if partial_scroll:
        top = mapped_rect(get_button, content).top()
        vertical.setValue(max(vertical.minimum(), top - 120))
        assert vertical.value() > vertical.minimum()
    else:
        vertical.setValue(vertical.minimum())
    _settle(qt_application, owner, apps, scroll)
    assert scroll.viewport().rect().contains(mapped_rect(get_button, scroll.viewport()))
    original_scroll = vertical.value()
    original_action_y = get_button.mapTo(scroll.viewport(), QPoint()).y()
    original_summary_y = apps.monkey_target_summary.mapTo(scroll.viewport(), QPoint()).y()
    positions = []
    vertical.valueChanged.connect(positions.append)
    requests = QSignalSpy(apps.monkey_preparation_requested)
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)

    def assert_no_jump(current_button):
        _settle(qt_application, owner, apps, scroll)
        assert vertical.value() == original_scroll
        assert all(value == original_scroll for value in positions), positions
        assert current_button.mapTo(scroll.viewport(), QPoint()).y() == original_action_y
        summary_y = apps.monkey_target_summary.mapTo(scroll.viewport(), QPoint()).y()
        assert summary_y == original_summary_y
        assert current_button.hasFocus(), repr(qt_application.focusWidget())
        assert scroll.viewport().rect().contains(mapped_rect(current_button, scroll.viewport()))

    QTest.mouseClick(get_button, Qt.MouseButton.LeftButton, pos=get_button.rect().center())
    pending = apps._monkey_preparation
    assert pending is not None and requests.count() == 1
    assert not apps.monkey_events.isEnabled()
    assert_no_jump(cancel_button)
    if terminal == "cancel":
        QTest.mouseClick(
            cancel_button, Qt.MouseButton.LeftButton, pos=cancel_button.rect().center(),
        )
        assert pending.cancellation.is_cancelled
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    elif terminal == "failure":
        apps.on_monkey_preparation_finished(
            pending.request_id, {"success": False, "error": "获取测试包信息失败，请重试"},
        )
        assert "获取测试包信息失败，请重试" in apps.monkey_package_info.text()
    else:
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    assert apps._monkey_preparation is None
    assert starts.count() == 0 and requests.count() == 1
    assert_no_jump(get_button)
    assert get_button.isEnabled() and get_button.isVisible()
    assert not cancel_button.isEnabled() and not cancel_button.isVisible()
    assert apps.start_monkey_btn.isEnabled()
    assert apps.monkey_events.isEnabled()


@pytest.mark.parametrize("width,font_size,terminal", [
    (900, 12, "success"), (420, 22, "failure"),
])
def test_query_completion_preserves_focus_moved_to_another_control(
    qt_application, monkey_page, width, font_size, terminal,
):
    """用户等待时已回到包名输入，完成回调不得把焦点和滚动位置抢回查询按钮。"""
    owner, apps, scroll, content = monkey_page(width, font_size)
    get_button = apps.monkey_get_package_btn
    actual_window = get_button.window()
    actual_window.activateWindow()
    wait_until(qt_application, lambda: qt_application.activeWindow() is actual_window)
    scroll.verticalScrollBar().setValue(mapped_rect(get_button, content).top() - 120)
    _settle(qt_application, owner, apps, scroll)
    assert scroll.viewport().rect().contains(mapped_rect(get_button, scroll.viewport()))
    requests = QSignalSpy(apps.monkey_preparation_requested)
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    QTest.mouseClick(get_button, Qt.MouseButton.LeftButton, pos=get_button.rect().center())
    pending = apps._monkey_preparation
    assert pending is not None
    _settle(qt_application, owner, apps, scroll)
    field = apps.program_edit
    scroll.verticalScrollBar().setValue(mapped_rect(field, content).top() - 80)
    _settle(qt_application, owner, apps, scroll)
    assert scroll.viewport().rect().contains(mapped_rect(field, scroll.viewport()))
    QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=field.rect().center())
    wait_until(qt_application, field.hasFocus)
    _settle(qt_application, owner, apps, scroll)
    original_scroll = scroll.verticalScrollBar().value()
    positions = []
    scroll.verticalScrollBar().valueChanged.connect(positions.append)
    result = (
        _success(pending) if terminal == "success"
        else {"success": False, "error": "获取测试包信息失败，请重试"}
    )
    apps.on_monkey_preparation_finished(pending.request_id, result)
    _settle(qt_application, owner, apps, scroll)
    assert field.hasFocus()
    assert apps._monkey_preparation is None
    assert get_button.isEnabled() and get_button.isVisible()
    assert not apps.monkey_cancel_prepare_btn.isVisible()
    assert apps.monkey_events.isEnabled()
    assert starts.count() == 0 and requests.count() == 1
    assert scroll.verticalScrollBar().value() == original_scroll
    assert all(value == original_scroll for value in positions), positions


def test_keyboard_package_query_and_cancel_keep_focus_and_viewport(
    qt_application, monkey_page,
):
    """空格键可启动并取消查询，替换按钮保持键盘焦点且晚到结果不改变已取消状态。"""
    owner, apps, scroll, content = monkey_page(420, 22)
    get_button = apps.monkey_get_package_btn
    cancel_button = apps.monkey_cancel_prepare_btn
    actual_window = get_button.window()
    actual_window.activateWindow()
    wait_until(qt_application, lambda: qt_application.activeWindow() is actual_window)
    vertical = scroll.verticalScrollBar()
    vertical.setValue(mapped_rect(get_button, content).top() - 120)
    _settle(qt_application, owner, apps, scroll)
    get_button.setFocus(Qt.FocusReason.TabFocusReason)
    _settle(qt_application, owner, apps, scroll)
    assert get_button.hasFocus()
    assert scroll.viewport().rect().contains(mapped_rect(get_button, scroll.viewport()))
    original_scroll = vertical.value()
    positions = []
    vertical.valueChanged.connect(positions.append)
    requests = QSignalSpy(apps.monkey_preparation_requested)
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)

    QTest.keyClick(get_button, Qt.Key.Key_Space)
    pending = apps._monkey_preparation
    assert pending is not None and requests.count() == 1
    _settle(qt_application, owner, apps, scroll)
    assert cancel_button.hasFocus() and cancel_button.isEnabled()
    assert vertical.value() == original_scroll
    QTest.keyClick(cancel_button, Qt.Key.Key_Space)
    assert pending.cancellation.is_cancelled
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    _settle(qt_application, owner, apps, scroll)
    assert apps._monkey_preparation is None
    assert get_button.hasFocus() and get_button.isEnabled()
    assert apps.monkey_events.isEnabled()
    assert starts.count() == 0 and requests.count() == 1
    assert vertical.value() == original_scroll
    assert all(value == original_scroll for value in positions), positions


@pytest.mark.parametrize("initial_width,font_size", [(900, 12), (900, 22), (292, 22)])
def test_preset_has_no_surplus_height_on_first_show_or_width_round_trip(
    qt_application, monkey_page, initial_width, font_size,
):
    """方案容器不保存首次布局的膨胀高度，宽窄往返仅随真实操作行数增减。"""
    owner, apps, scroll, _content = monkey_page(initial_width, font_size, "Microsoft YaHei UI")
    preset = apps.monkey_preset_bar
    fields = apps.monkey_parameter_binding._container_ref()
    for width in (initial_width, 900, 292, 900):
        if width != initial_width or scroll.viewport().width() != width:
            _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        _settle(qt_application, owner, apps, scroll)
        row = _assert_compact_preset_row(apps)
        assert_non_overlapping(
            (apps.monkey_parameters_heading, preset, fields), apps.monkey_parameters_card,
        )
        for control in (preset.combo, preset.load_button, preset.save_button, preset.delete_button):
            assert_contained(control, preset)
        heading_rect = mapped_rect(apps.monkey_parameters_heading, apps.monkey_parameters_card)
        row_rect = mapped_rect(row, apps.monkey_parameters_card)
        fields_rect = mapped_rect(fields, apps.monkey_parameters_card)
        spacing = apps.monkey_parameters_card.layout().spacing()
        if not row.isAncestorOf(apps.monkey_parameters_heading):
            assert row_rect.top() - heading_rect.bottom() - 1 <= spacing
        assert fields_rect.top() - row_rect.bottom() - 1 <= spacing


@pytest.mark.parametrize("initial_width,target_width", [(292, 900), (900, 292)])
def test_hidden_preset_does_not_keep_previous_width_height(
    qt_application, monkey_page, initial_width, target_width,
):
    """隐藏页调整宿主宽度后首次显示，方案的旧行高不得锁定为新布局的最小高度。"""
    owner, apps, scroll, _content = monkey_page(initial_width, 22, "Microsoft YaHei UI")
    actual_window = apps.monkey_preset_bar.window()
    actual_window.hide()
    actual_window.resize(target_width, actual_window.height())
    qt_application.processEvents()
    actual_window.show()
    _resize_feature_viewport(qt_application, owner, apps, scroll, target_width)
    _settle(qt_application, owner, apps, scroll)
    _assert_compact_preset_row(apps)


def test_preset_row_rejects_transient_height_from_parent_allocation(
    qt_application, monkey_page,
):
    """布局暂时按旧换行高度分配子控件时，只能保留当前宽度所需的语义高度。"""
    owner, apps, scroll, _content = monkey_page(900, 22, "Microsoft YaHei UI")
    preset = apps.monkey_preset_bar
    natural_height = preset.heightForWidth(preset.width())
    previous_narrow_height = preset.heightForWidth(274)
    assert previous_narrow_height > natural_height
    preset.setFixedHeight(previous_narrow_height)
    preset.resize(preset.width() - 1, previous_narrow_height)
    _settle(qt_application, owner, apps, scroll)
    _assert_compact_preset_row(apps)
