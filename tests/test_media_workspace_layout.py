"""截图页在真实工作区内保持统一边距及设备操作、画布、图片操作顺序。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from gui.styles import BaseStyles
from tests import test_page_scroll_edges as scroll_edges
from tests.screenshot_helpers import wait_for_screenshot
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui
edge_frame = scroll_edges.edge_frame


@pytest.mark.parametrize("size,theme", [((1120, 720), "Light"), ((860, 500), "Dark")])
def test_media_workspace_reaches_balanced_content_edges(
    edge_frame, qt_application, tmp_path, size, theme,
):
    frame = edge_frame
    frame.resize(*size)
    BaseStyles.switch_theme(theme)
    # 离屏平台没有系统云母背景，实色模式仍使用实际主题和完整窗口布局。
    frame.setMicaEffectEnabled(False)
    assert frame._open_workspace_feature("apps", "media")
    host = frame._workspace_feature_hosts["apps"]
    page = host.stack.currentWidget()
    apps = frame.left_panel._apps_tab
    wait_until(qt_application, lambda: page.isVisibleTo(frame))
    wait_until(qt_application, lambda: scroll_edges._animation_finished(frame))
    picture = QPixmap(360, 640)
    picture.fill(Qt.GlobalColor.darkGray)
    image_path = tmp_path / "portrait.png"
    assert picture.save(str(image_path))
    page.receive_payload([str(image_path)])
    wait_for_screenshot(page)
    tools = (
        apps.btn_screenshot, apps.record_duration, apps.btn_screen_record, apps.btn_stop_record,
    )
    wait_for_stable_geometry(
        qt_application, (frame, page, page._canvas_frame, page._command_bar, *tools),
    )
    assert mapped_rect(apps.btn_screenshot, page).top() == 8
    assert mapped_rect(apps.btn_screenshot, page).left() == 32
    assert not page.isAncestorOf(apps.email_text_sender)
    assert not page.isAncestorOf(apps.btn_send_text)
    assert all(page.isAncestorOf(widget) for widget in tools)
    canvas = mapped_rect(page._canvas_frame, frame)
    commands = mapped_rect(page._command_bar, frame)
    assert canvas.bottom() < commands.top()
    assert frame.rect().bottom() - commands.bottom() == 8
    assert frame.rect().right() - commands.right() == 32
    assert host.content_scroll.verticalScrollBar().maximum() == 0
    assert host.content_scroll.horizontalScrollBar().maximum() == 0
    assert page._add_action.isEnabled()
