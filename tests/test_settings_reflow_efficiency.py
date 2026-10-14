"""设置卡动画只裁切高度，不重复改变正文的换行宽度。"""

import pytest
from PySide6.QtCore import QEvent, QObject

from tests.test_settings_expand_animation import make_page as make_page
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width,font_size", [(978, 12), (420, 22)])
def test_height_only_resize_keeps_setting_cards_in_place(
    qt_application, make_page, monkeypatch, width, font_size,
):
    page = make_page(width, font_size)
    calls = []
    for presentation in page._card_presentations:
        original = presentation.reflow

        def record(value, original=original):
            calls.append(value)
            original(value)

        monkeypatch.setattr(presentation, "reflow", record)
    for height in (680, 540, 740):
        page.resize(width, height)
        wait_for_stable_geometry(qt_application, (page, page.widget()))
    assert calls == [], "纯高度变化不能重复测量、重挂普通设置卡"

    page.resize(width + 100, page.height())
    wait_for_stable_geometry(qt_application, (page, page.widget()))
    assert calls, "真实宽度变化必须继续重新布局"


def test_same_width_explicit_reflow_keeps_updated_setting_text_readable(qt_application, make_page):
    page = make_page(420, 22)
    card = page.scan_card
    before = card.height()
    description = "设备发现状态更新后的详细说明。" * 15
    card.setContent(description)
    page._reflow_settings()
    wait_for_stable_geometry(qt_application, (page, page.widget(), card))
    assert card.contentLabel.text() == description
    assert card.height() > before
    assert card.contentLabel.height() >= card.contentLabel.heightForWidth(
        card.contentLabel.width(),
    )


class _WidthChanges(QObject):
    """记录真正的宽度变化，避免仅检查每帧最终值掩盖同步往返。"""

    def __init__(self, widgets, parent):
        super().__init__(parent)
        self.changes = []
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and event.size().width() != event.oldSize().width():
            self.changes.append((
                type(watched).__name__, event.oldSize().width(), event.size().width(),
            ))
        return False


@pytest.mark.parametrize("width,font_size", [(978, 12), (420, 22)])
@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
def test_animation_keeps_content_width_stable_until_page_width_changes(
    qt_application, make_page, width, font_size, card_name,
):
    page = make_page(width, font_size)
    card = getattr(page, card_name)
    page.ensureWidgetVisible(card.card.expandButton, 0, 0)
    qt_application.processEvents()
    observer = _WidthChanges((card.scrollWidget, card.view, *card.widgets), card)
    content_width = card.scrollWidget.width()
    for expanded in (True, False):
        card.setExpand(expanded)
        card.expandAni.pause()
        card.card.expandButton.rotateAni.pause()
        for time_ms in (0, 40, 80, 120, 160, 200):
            card.expandAni.setCurrentTime(time_ms)
            qt_application.processEvents()
            assert card.scrollWidget.width() == content_width
    assert observer.changes == [], observer.changes

    page.resize(width + 120, page.height())
    wait_for_stable_geometry(qt_application, (page, card, card.scrollWidget, card.view))
    assert card.card.width() == card.width()
    assert card.scrollWidget.width() == card.viewport().width()
    assert card.scrollWidget.width() > content_width
    assert observer.changes, "真实窗口宽度变化仍必须更新正文布局"
