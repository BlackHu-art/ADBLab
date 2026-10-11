"""设置、系统高级区和设备详情的原位展开边界，不要求不同功能内容等高。"""

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLabel

from gui.styles import BaseStyles
from tests.test_device_hub_page import _rich_metadata, _show_page
from tests.test_settings_expand_animation import make_page as make_page
from tests.test_system_panel_categories import _build_system_panel
from tests.ui_geometry_helpers import mapped_rect, wait_until

pytestmark = pytest.mark.ui


def _geometry_in(widget, owner):
    position = widget.mapTo(owner, QPoint())
    return position.x(), position.y(), widget.width(), widget.height()


class _PaintGeometry(QObject):
    def __init__(self, owner, widgets):
        super().__init__(owner)
        self.owner = owner
        self.frames = {widget: [] for widget in widgets}
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.frames[watched].append(_geometry_in(watched, self.owner))
        return False

    def assert_unchanged(self, before):
        for widget, frames in self.frames.items():
            assert frames, widget.objectName()
            assert set(frames) == {before[widget]}, (widget, before[widget], frames)


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
@pytest.mark.parametrize("opening", [True, False], ids=["opening-to-closing", "closing-to-opening"])
@pytest.mark.parametrize("width,font_size", [(978, 12), (420, 22)])
def test_settings_reverse_keeps_current_card_height_before_next_frame(
    qt_application, make_page, card_name, opening, width, font_size,
):
    page = make_page(width, font_size)
    card = getattr(page, card_name)
    page.ensureWidgetVisible(card.card.expandButton, 0, 0)
    qt_application.processEvents()
    collapsed_height = card.height()
    card.setExpand(True)
    expanded_height = None
    if not opening:
        card.expandAni.setCurrentTime(card.expandAni.duration())
        qt_application.processEvents()
        expanded_height = card.height()
        card.setExpand(False)
    card.expandAni.pause()
    card.card.expandButton.rotateAni.pause()
    card.expandAni.setCurrentTime(round(card.expandAni.duration() * .4))
    card.card.expandButton.rotateAni.setCurrentTime(
        round(card.card.expandButton.rotateAni.duration() * .4),
    )
    qt_application.processEvents()
    current_height = card.height()
    current_angle = card.card.expandButton.angle
    assert current_height > collapsed_height

    card.setExpand(not opening)

    # 直接观察反向入口返回时的几何，不能先推进时间把同步终点跳动掩盖掉。
    assert card.height() == current_height
    assert card.card.expandButton.angle == current_angle
    card.expandAni.setCurrentTime(card.expandAni.duration())
    card.card.expandButton.rotateAni.setCurrentTime(card.card.expandButton.rotateAni.duration())
    qt_application.processEvents()
    # 回到相同宽度和字体下的原完整状态，不拿 resize 中间宽度缓存的 sizeHint 作终点。
    target_height = collapsed_height if opening else expanded_height
    assert card.height() == target_height
    assert card.card.expandButton.angle == (0 if opening else 180)
    if not opening:
        for row in card.widgets:
            for control in row.findChildren(QLabel) + row.findChildren(QAbstractButton):
                assert card.viewport().rect().contains(mapped_rect(control, card.viewport()))


@pytest.mark.parametrize("font_size", [12, 22])
def test_device_details_toggle_does_not_move_existing_header_or_summary(
    qt_application, monkeypatch, font_size,
):
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    window, page = _show_page(qt_application, 960)
    page.set_device_metadata(_rich_metadata())
    QTest.qWait(40)
    card = page.device_cards[0]
    widgets = [card.name_label, card.brand_label, card.status_label]
    widgets.extend(field.value for field in card.summary_fields.values())
    before = {widget: _geometry_in(widget, card) for widget in widgets}
    observer = _PaintGeometry(card, widgets)
    original_cards = page.device_cards
    try:
        for expanded in (True, False, True, False):
            card.details_button.click()
            wait_until(qt_application, lambda: not card._details_transition_active)
            assert card.details_container.isVisibleTo(card) is expanded
            assert page.device_cards == original_cards
            assert all(_geometry_in(widget, card) == before[widget] for widget in widgets), [
                (before[widget], _geometry_in(widget, card)) for widget in widgets
            ]
        observer.assert_unchanged(before)
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("font_size", [12, 22])
def test_intent_advanced_toggle_keeps_leading_fields_and_draft_in_place(
    qt_application, isolated_app_settings, font_size,
):
    isolated_app_settings.set_many({"ui_font_size": font_size, "font_family": "Microsoft YaHei"})
    BaseStyles.reload_from_settings()
    panel, window = _build_system_panel()
    form = panel.intent_controls
    window.resize(1000, 1800)
    window.show()
    panel.apply_responsive_width(1000)
    form.data_uri.setText("demo://stable/draft")
    form.flags.setText("0x10000000")
    QTest.qWait(40)
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    card = next(
        card for card in panel._system_section_groups
        if card.headerLabel.text() == "广播与 Intent"
    )
    widgets = [form.activity_mode, panel.activity_spec, panel.btn_start_activity]
    before = {widget: _geometry_in(widget, card) for widget in widgets}
    observer = _PaintGeometry(card, widgets)
    try:
        for expanded in (True, False, True, False):
            form.advanced_toggle.click()
            QTest.qWait(40)
            wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
            assert form.advanced.isVisibleTo(card) is expanded
            assert form.data_uri.text() == "demo://stable/draft"
            assert form.flags.text() == "0x10000000"
            assert all(_geometry_in(widget, card) == before[widget] for widget in widgets), [
                (before[widget], _geometry_in(widget, card)) for widget in widgets
            ]
        observer.assert_unchanged(before)
    finally:
        window.close()
        window.deleteLater()
