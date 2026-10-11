"""设备详情按自然内容裁切，逐帧移动后续设备卡并收口隐藏生命周期。"""

from contextlib import contextmanager
from dataclasses import replace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QVBoxLayout, QWidget
from shiboken6 import isValid

from gui.pages.device_hub import DeviceHubPage
from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_device_hub_page import _capture_copied_details, _rich_metadata
from tests.ui_geometry_helpers import mapped_rect, wait_until

pytestmark = pytest.mark.ui


@contextmanager
def _details_page(app, width=960, font_size=12):
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    host = QWidget()
    host.resize(width, 1500)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    page = DeviceHubPage(host)
    layout.addWidget(page)
    records = _rich_metadata()
    page.set_device_metadata(records)
    page.set_device_context([], [record["ip"] for record in records], "ready")
    host.show()
    host.activateWindow()
    for _ in range(3):
        app.processEvents()
    try:
        yield host, page, page.device_cards[0], records
    finally:
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _advance(app, card, fraction):
    animation = card._details_animation
    if animation.state() == QAbstractAnimation.State.Running:
        animation.pause()
    animation.setCurrentTime(round(animation.duration() * fraction))
    for _ in range(3):
        app.processEvents()


class _PaintPositions(QObject):
    def __init__(self, card, widgets):
        super().__init__(card)
        self.card = card
        self.positions = {widget: [] for widget in widgets}
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            point = watched.mapTo(self.card, QPoint())
            self.positions[watched].append((
                point.x(), point.y(), watched.width(), watched.height(),
            ))
        return False


@pytest.mark.parametrize("width,font_size", [(960, 12), (480, 22)])
def test_details_reveal_keeps_text_fixed_and_following_card_in_sync(
    qt_application, width, font_size,
):
    with _details_page(qt_application, width, font_size) as (_host, page, card, _records):
        sibling = page.device_cards[1]
        collapsed = card.height()
        sibling_y = sibling.y()
        fields = [card.name_label, card.summary_fields["system"].value]
        fields.extend(field.value for field in card.detail_fields.values())
        observer = _PaintPositions(card, fields)
        card.details_button.click()
        animation = getattr(card, "_details_animation", None)
        assert animation is not None and animation.state() == QAbstractAnimation.State.Running
        assert card.height() == collapsed
        heights = []
        for fraction in (0, .2, .4, .6, .8, 1):
            _advance(qt_application, card, fraction)
            heights.append(card.height())
            assert sibling.y() - sibling_y == card.height() - collapsed
        assert heights[0] == collapsed and heights[0] < heights[1] < heights[-1]
        for widget, positions in observer.positions.items():
            assert positions and len(set(positions)) == 1, (widget, positions)
        assert card._details_clip.rect().contains(
            mapped_rect(card.copy_details_button, card._details_clip),
        )
        for positions in observer.positions.values():
            positions.clear()
        card.details_button.click()
        heights = []
        for fraction in (0, .2, .4, .6, .8, 1):
            _advance(qt_application, card, fraction)
            heights.append(card.height())
            assert sibling.y() - sibling_y == card.height() - collapsed
        assert heights[0] > heights[1] > heights[-1] == collapsed
        assert card.details_container.isHidden() and card._details_clip.height() == 0
        for widget, positions in observer.positions.items():
            assert positions and len(set(positions)) == 1, (widget, positions)
        assert not card._details_clip.autoFillBackground()
        assert not card.details_container.autoFillBackground()


@pytest.mark.parametrize("opening", [True, False])
def test_details_reverse_continues_from_current_height(qt_application, opening):
    with _details_page(qt_application, 620, 22) as (_host, _page, card, _records):
        collapsed = card.height()
        card.details_button.click()
        _advance(qt_application, card, 1)
        expanded = card.height()
        card.details_button.click()
        if opening:
            _advance(qt_application, card, 1)
            card.details_button.click()
        _advance(qt_application, card, .4)
        current = (card.height(), card._details_clip.height())
        assert collapsed < card.height() < expanded
        card.details_button.click()
        assert (card.height(), card._details_clip.height()) == current
        _advance(qt_application, card, 1)
        assert card.height() == (collapsed if opening else expanded)
        assert not card._details_transition_active


@pytest.mark.parametrize("action", ["hide", "close", "remove"])
def test_hidden_or_removed_card_stops_details_animation(qt_application, action):
    with _details_page(qt_application) as (host, page, card, records):
        card.details_button.click()
        _advance(qt_application, card, .4)
        animation = card._details_animation
        if action == "remove":
            page.set_device_context([], [records[1]["ip"]], "ready")
        else:
            getattr(host, action)()
        assert animation.state() == QAbstractAnimation.State.Stopped
        assert not card._details_transition_active
        if action == "remove":
            assert isValid(card) and card.isHidden()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not isValid(card)
        else:
            host.show()
            qt_application.processEvents()
            assert card.details_button.isChecked()
            assert animation.state() == QAbstractAnimation.State.Stopped
            assert card._details_clip.rect().contains(
                mapped_rect(card.copy_details_button, card._details_clip),
            )


def test_details_keyboard_focus_completes_reveal_and_returns_on_collapse(qt_application):
    with _details_page(qt_application) as (_host, _page, card, _records):
        card.details_button.click()
        _advance(qt_application, card, .3)
        card.copy_details_button.setFocus(Qt.FocusReason.TabFocusReason)
        qt_application.processEvents()
        assert card._details_animation.state() == QAbstractAnimation.State.Stopped
        assert card._details_clip.rect().contains(
            mapped_rect(card.copy_details_button, card._details_clip),
        )
        assert card.copy_details_button.hasFocus()
        card.details_button.setChecked(False)
        assert card.details_button.hasFocus()
        assert card.copy_details_button.focusPolicy() == Qt.FocusPolicy.NoFocus
        _advance(qt_application, card, 1)


def test_multiple_details_animations_release_page_only_after_last_card(qt_application):
    with _details_page(qt_application) as (_host, page, card, _records):
        sibling = page.device_cards[1]
        transitions = QSignalSpy(page.details_transition_changed)
        card.details_button.click()
        sibling.details_button.click()
        _advance(qt_application, card, 1)
        assert transitions.count() == 1 and transitions.at(0) == [True]
        _advance(qt_application, sibling, 1)
        assert [transitions.at(index) for index in range(transitions.count())] == [[True], [False]]


def test_details_refresh_and_font_resize_retarget_without_losing_current_snapshot(qt_application):
    with _details_page(qt_application) as (host, page, card, records):
        card.details_button.click()
        _advance(qt_application, card, .4)
        records[0]["Storage Available"] = "19 GiB"
        page.set_device_metadata(records)
        assert page.device_cards[0] is card and card.details_button.isChecked()
        assert card.detail_fields["Storage Available"].full_value() == "19 GiB"
        config = replace(BaseStyles.current_font_config(), ui_size=22)
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        host.resize(480, 1500)
        qt_application.processEvents()
        _advance(qt_application, card, 1)
        wait_until(qt_application, lambda: not card._details_transition_active)
        assert card.copy_details_button.font().pointSize() == 22
        for field in (*card.detail_fields.values(), card.identifier_field):
            assert card._details_clip.rect().contains(mapped_rect(field, card._details_clip))
        assert card._details_clip.rect().contains(
            mapped_rect(card.copy_details_button, card._details_clip),
        )
        card.copy_details_button.setFocus(Qt.FocusReason.TabFocusReason)
        assert card.copy_details_button.hasFocus()


def test_shutdown_while_window_is_visible_stops_details_and_rejects_late_restart(
    qt_application, monkeypatch,
):
    copied = _capture_copied_details(monkeypatch)
    with _details_page(qt_application) as (host, page, card, records):
        sibling = page.device_cards[1]
        transitions = QSignalSpy(page.details_transition_changed)
        for target in (card, sibling):
            target.details_button.click()
            _advance(qt_application, target, .4)
            target._copy_feedback_timer.start(1800)
        page.prepare_shutdown()
        page.prepare_shutdown()
        assert host.isVisible()
        assert not page._active_detail_cards
        assert [transitions.at(index) for index in range(transitions.count())] == [[True], [False]]
        for target in (card, sibling):
            assert not target._details_transition_active
            assert target._details_animation.state() == QAbstractAnimation.State.Stopped
            assert not target._copy_feedback_timer.isActive()
            assert target.details_button.isChecked()
            target.details_button.click()
            assert target.details_button.isChecked()
            target.copy_details_button.click()
            assert not target._copy_feedback_timer.isActive()
        assert copied == []
        records[0]["Storage Available"] = "18 GiB"
        page.set_device_metadata(records)
        qt_application.processEvents()
        assert card.detail_fields["Storage Available"].full_value() == "18 GiB"
        assert card._details_animation.state() == QAbstractAnimation.State.Stopped
        assert transitions.count() == 2
