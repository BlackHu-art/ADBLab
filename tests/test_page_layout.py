"""首页卡片与无标题占位页面在实际字体度量下的布局回归。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, PushButton

from core.settings_manager import AppSettings
from gui.pages.fluent_pages import ActionCardView, DeviceContextCard, GalleryPage, HomePage
from gui.styles import BaseStyles, FontRole
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until


@pytest.fixture
def page_font_settings(monkeypatch, qt_application):
    values = {"font_family": "Microsoft YaHei", "ui_font_size": 12, "log_font_size": 9}
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda cls: SimpleNamespace(get=values.get))
    )
    BaseStyles.reload_from_settings()
    return values


@pytest.mark.parametrize("width,font_size", [(1050, 12), (420, 22), (300, 22)])
def test_action_cards_fill_available_row_and_keep_wrapped_text_visible(
    qt_application, page_font_settings, width, font_size,
):
    page_font_settings["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    view = ActionCardView("常用工具")
    cards = [
        view.add_card(
            FluentIcon.FOLDER,
            f"文件管理 {index}",
            "浏览设备文件并传输内容，支持返回与键盘操作",
            lambda: None,
        )
        for index in range(6)
    ]
    view.resize(width, 900)
    view.show()
    wait_until(qt_application, lambda: cards[-1].geometry().bottom() > cards[0].geometry().bottom())
    qt_application.processEvents()

    first_row = [card for card in cards if card.y() == cards[0].y()]
    right_margin = view.width() - max(card.geometry().right() for card in first_row) - 1
    assert 32 <= right_margin <= 36
    assert all(card.geometry().left() >= 32 for card in cards)
    assert all(card.geometry().right() < view.width() - 30 for card in cards)
    for card in cards:
        assert card.title_label.font().pointSize() == font_size
        for label in (card.title_label, card.content_label):
            assert label.height() >= label.heightForWidth(label.width())
            top_left = label.mapTo(card, QPoint(0, 0))
            assert top_left.y() >= 0
            assert top_left.y() + label.height() <= card.height()


def test_action_card_font_change_preserves_identity_focus_and_activation(
    qt_application, page_font_settings,
):
    view = ActionCardView("常用工具")
    callback = Mock()
    card = view.add_card(FluentIcon.FOLDER, "文件管理", "浏览设备文件并传输内容", callback)
    view.resize(420, 500)
    view.show()
    card.setFocus()
    qt_application.processEvents()
    initial_height = card.height()
    page_font_settings["ui_font_size"] = 22
    BaseStyles.reload_from_settings()
    wait_until(qt_application, lambda: card.height() > initial_height)
    assert card.hasFocus()
    assert view.findChildren(type(card)) == [card]
    focus_pixel = card.grab().toImage().pixelColor(3, card.height() // 2)
    assert focus_pixel.name().lower() == BaseStyles.color("BORDER_FOCUS").lower()
    QTest.keyClick(card, Qt.Key.Key_Return)
    callback.assert_called_once_with()


@pytest.mark.parametrize("scroll", [False, True])
def test_gallery_content_uses_full_page_and_keeps_large_font_action_accessible(
    qt_application, page_font_settings, scroll,
):
    page_font_settings["ui_font_size"] = 22
    BaseStyles.reload_from_settings()
    content = QWidget()
    layout = QVBoxLayout(content)
    action = PushButton("已选择设备")
    action.setFont(BaseStyles.font_for_role(FontRole.UI))
    callback = Mock()
    action.clicked.connect(callback)
    layout.addWidget(action)
    layout.addStretch(1)
    page = GalleryPage(
        "samplePage", "应用与自动化", "使用已选择设备执行操作", content, scroll=scroll,
    )
    page.resize(420, 600)
    page.show()
    wait_for_stable_geometry(qt_application, (page, page.body, content, action))

    assert page.accessibleName() == "应用与自动化"
    assert page.accessibleDescription() == "使用已选择设备执行操作"
    assert page.body.geometry() == page.rect()
    viewport = page.body.viewport() if scroll else page.body
    assert viewport.rect().contains(mapped_rect(action, viewport))
    assert action.isVisibleTo(page)
    assert action.font().pointSize() == 22
    assert action.height() >= action.fontMetrics().height()
    action.setFocus()
    assert action.hasFocus()
    QTest.keyClick(action, Qt.Key.Key_Space)
    callback.assert_called_once()


def test_device_context_uses_compact_height_and_follows_font_changes(
    qt_application, page_font_settings,
):
    card = DeviceContextCard()
    card.set_context([], [], "empty")
    card.resize(1100, card.sizeHint().height())
    card.show()
    qt_application.processEvents()
    assert card.heightForWidth(1100) <= 120
    assert card.summary_label.font().pointSize() == 12
    page_font_settings["ui_font_size"] = 22
    BaseStyles.reload_from_settings()
    card.resize(500, card.heightForWidth(500))
    qt_application.processEvents()
    assert card.summary_label.font().pointSize() == 22
    assert card.detail_label.font().pointSize() == 21
    assert card.manage_button.accessibleName() == "连接设备"
    assert card.manage_button.width() >= card.manage_button.minimumSizeHint().width()
    summary = card.summary_label
    assert summary.height() >= summary.heightForWidth(summary.width())


def test_home_wide_layout_does_not_keep_empty_vertical_scroll_range(
    qt_application, page_font_settings,
):
    page = HomePage(Mock())
    page.set_device_context([], [], "empty")
    page.resize(1220, 920)
    page.show()
    wait_until(qt_application, lambda: page.tool_cards["save_path"].width() > 300)
    wait_until(qt_application, lambda: page.verticalScrollBar().maximum() == 0)
    assert page.horizontalScrollBar().maximum() == 0
    assert page.verticalScrollBar().maximum() == 0
    tools = page.tool_cards["app_mgr"].parentWidget()
    assert tools is not None and tools.isVisibleTo(page)
    assert page.banner.mapTo(page.viewport(), QPoint()).y() == 0
    assert tools.mapTo(page.banner, QPoint()).y() > page.banner.title_label.geometry().bottom()
