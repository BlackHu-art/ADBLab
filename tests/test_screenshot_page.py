import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QSize, Qt
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QDialog, QWidget
from qfluentwidgets import (
    CommandBar,
    FluentIcon,
    HorizontalFlipView,
    HorizontalPipsPager,
    RoundMenu,
)

from gui.features.media import ScreenshotPage
from gui.pages.workspace_features import WorkspaceFeatureHost
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until


def _write_image(path, color: Qt.GlobalColor) -> str:
    image = QPixmap(48, 32)
    image.fill(color)
    assert image.save(str(path))
    return str(path)


def test_screenshot_flip_view_and_pips_share_navigation_and_batch_selection(
    qt_application, tmp_path,
):
    """主图、圆点和键盘共享当前截图，后台批次追加保留用户正在查看的图片。"""

    paths = [_write_image(tmp_path / f"device-{i}.png", color) for i, color in enumerate(
        (Qt.GlobalColor.red, Qt.GlobalColor.green, Qt.GlobalColor.blue)
    )]
    page = ScreenshotPage(paths[:2])
    try:
        page.resize(760, 620)
        page.show()
        qt_application.processEvents()
        view, pager = page._view, page._pager
        assert isinstance(view, HorizontalFlipView)
        assert isinstance(pager, HorizontalPipsPager)
        assert isinstance(page._command_bar, CommandBar)
        assert view.isVisibleTo(page) and pager.isVisibleTo(page)
        target = pager.visualItemRect(pager.item(1)).center()
        QTest.mouseClick(pager.viewport(), Qt.MouseButton.LeftButton, pos=target)
        assert page._current_path() == paths[1]
        assert view.currentIndex() == pager.currentIndex() == 1
        page.receive_payload({"paths": paths, "focus_new": False})
        assert page._current_path() == paths[1]
        view.setFocus()
        QTest.keyClick(view, Qt.Key.Key_End)
        assert page._current_path() == paths[2]
        assert page._nav_label.text() == "3 / 3"
        assert view.currentIndex() == pager.currentIndex() == 2
        page._delete_action.trigger()
        assert page._current_path() == paths[1]
        assert view.count() == pager.count() == 2
        assert view.currentIndex() == pager.currentIndex() == 1
        QTest.keyClick(view, Qt.Key.Key_Left)
        assert page._current_path() == paths[0]
        QTest.keyClick(view, Qt.Key.Key_Right)
        assert page._current_path() == paths[1]
        QTest.keyClick(pager, Qt.Key.Key_Home)
        assert page._current_path() == paths[0]
    finally:
        page.close()


def test_screenshot_flip_view_preserves_mixed_image_aspect_ratios(qt_application, tmp_path):
    """多设备横竖屏逐张完整显示，实际绘制尺寸保留原图比例和边缘。"""

    paths = []
    for name, size, color in (
        ("portrait", (540, 960), Qt.GlobalColor.red),
        ("landscape", (960, 320), Qt.GlobalColor.green),
    ):
        path = tmp_path / f"{name}.png"
        pixmap = QPixmap(*size)
        pixmap.fill(color)
        assert pixmap.save(str(path))
        paths.append(str(path))
    page = ScreenshotPage(paths)
    try:
        page.resize(760, 660)
        page.show()
        view = page._view
        wait_for_stable_geometry(qt_application, (page, view))
        for index, rgb, ratio in ((0, (255, 0, 0), 540 / 960), (1, (0, 255, 0), 3)):
            view.setCurrentIndex(index)
            page._reset_zoom()
            wait_until(qt_application, lambda: (
                view.scrollBar.ani.state() == QAbstractAnimation.State.Stopped
            ))
            rendered = view.viewport().grab().toImage()
            points = [
                (x, y)
                for y in range(rendered.height())
                for x in range(rendered.width())
                if rendered.pixelColor(x, y).getRgb()[:3] == rgb
            ]
            assert points, "主图必须实际绘制截图"
            width = max(p[0] for p in points) - min(p[0] for p in points) + 1
            height = max(p[1] for p in points) - min(p[1] for p in points) + 1
            assert abs(width - height * ratio) <= 2
            drawn = view.delegate.itemSize(index)
            assert abs(width / rendered.devicePixelRatio() - drawn.width()) <= 2
            assert abs(height / rendered.devicePixelRatio() - drawn.height()) <= 2
            assert drawn.width() <= view.viewport().width()
            assert drawn.height() <= view.viewport().height()
            assert view.item(index).data(Qt.ItemDataRole.AccessibleTextRole)
    finally:
        page.close()


def test_screenshot_flip_view_keeps_eight_image_navigation_visible_through_resize_and_delete(
    qt_application, tmp_path,
):
    """八图批次在窗口缩放后仍能到达末图，逐张删除到零保留可继续添加的空态。"""

    paths = [
        _write_image(tmp_path / f"device-{index}.png", Qt.GlobalColor.blue)
        for index in range(8)
    ]
    page = ScreenshotPage([])
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    try:
        page.resize(1100, 760)
        page.show()
        view, pager = page._view, page._pager
        wait_for_stable_geometry(qt_application, (page, view))
        page.receive_payload(paths)
        wait_for_stable_geometry(qt_application, (page, view, pager))

        target = pager.visualItemRect(pager.item(2)).center()
        QTest.mouseClick(pager.viewport(), Qt.MouseButton.LeftButton, pos=target)
        assert page._current_path() == paths[2]
        QTest.mouseClick(view.nextButton, Qt.MouseButton.LeftButton)
        assert page._current_path() == paths[3]
        QTest.mouseClick(view.preButton, Qt.MouseButton.LeftButton)
        assert page._current_path() == paths[2]

        def current_image_is_visible():
            return (
                view.scrollBar.ani.state() == QAbstractAnimation.State.Stopped
                and view.viewport().rect().adjusted(-2, -2, 2, 2).contains(
                    view.visualItemRect(view.item(view.currentIndex()))
                )
            )

        QTest.keyClick(view, Qt.Key.Key_End)
        wait_until(qt_application, current_image_is_visible)
        page._zoom_in_action.trigger()
        manual_zoom = page._zoom_factor
        for width in (1100, 750, 1000):
            page.resize(width, 760)
            wait_for_stable_geometry(qt_application, (page, view, pager))
            assert page._current_path() == paths[-1]
            assert view.currentIndex() == pager.currentIndex() == 7
            assert page._zoom_factor == manual_zoom
            wait_until(qt_application, current_image_is_visible)

        while view.count() > 2:
            page._delete_action.trigger()
        assert page.image_paths == tuple(paths[:2])
        assert view.currentIndex() == pager.currentIndex() == 1
        wait_until(qt_application, current_image_is_visible)
        while page.image_paths:
            page._delete_action.trigger()
        assert view.count() == pager.count() == 0
        assert page._nav_label.text() == "0 / 0"
        assert page._image_stack.currentWidget() is page._empty_label
        assert page._empty_label.isVisibleTo(page)
        assert page._add_action.isEnabled()
        assert not any(action.isEnabled() for action in (
            page._copy_action, page._delete_action, page._rotate_action,
            page._zoom_in_action, page._info_action,
        ))
    finally:
        page.close()


def test_screenshot_command_bar_overflow_shares_action_state(qt_application, tmp_path):
    """窄窗菜单复用原始命令，信息勾选和单击删除后的禁用同步到全部入口。"""

    path = _write_image(tmp_path / "commands.png", Qt.GlobalColor.blue)
    page = ScreenshotPage([path])
    try:
        page.resize(380, 620)
        page.show()
        bar = page._command_bar
        wait_for_stable_geometry(qt_application, (page, bar))
        assert bar.moreButton.isVisibleTo(page)
        buttons = {button.action(): button for button in bar.commandButtons}
        QTest.mouseClick(bar.moreButton, Qt.MouseButton.LeftButton)
        menu = next(menu for menu in bar.findChildren(RoundMenu) if menu.isVisible())
        assert page._copy_action in menu.menuActions()
        assert page._delete_action in menu.menuActions()
        assert page._info_action in menu.menuActions()
        assert all(action in bar.actions() for action in menu.menuActions())
        page._info_action.trigger()
        qt_application.processEvents()
        assert page._info_action.isChecked()
        assert page._info_label.isVisibleTo(page)
        assert buttons[page._info_action].isChecked()
        metadata = page._info_label.text()
        page._info_action.trigger()
        assert page._info_label.isHidden()
        assert page._info_label.text() == metadata

        page._delete_action.trigger()
        assert not os.path.exists(path)
        for action in (page._copy_action, page._delete_action, page._info_action):
            assert not action.isEnabled()
            assert not buttons[action].isEnabled()
            assert action in menu.menuActions()
        menu.close()
    finally:
        page.close()


def test_screenshot_rotation_copies_display_direction_without_rewriting_original(
    qt_application, tmp_path,
):
    """旋转和复制使用完整图片，适应窗口的缩放及四次旋转都不改动原文件。"""

    path = tmp_path / "rotate.png"
    _write_image(path, Qt.GlobalColor.red)
    original_bytes = path.read_bytes()
    original = QPixmap(str(path)).toImage()
    page = ScreenshotPage([str(path)])
    try:
        page.resize(760, 620)
        page.show()
        page._rotate_action.trigger()
        expected = original.transformed(QTransform().rotate(90))
        assert page._original_pixmap.toImage() == original
        assert page._display_pixmap.toImage() == expected
        assert page._display_pixmap.size() == QSize(original.height(), original.width())
        page._copy_action.trigger()
        assert qt_application.clipboard().pixmap().toImage() == expected
        assert path.read_bytes() == original_bytes
        for _ in range(3):
            page._rotate_action.trigger()
        assert page._display_pixmap.toImage() == original
        assert path.read_bytes() == original_bytes
    finally:
        page.close()


def test_screenshot_add_images_cancellation_and_invalid_files_preserve_current_image(
    qt_application, tmp_path, monkeypatch,
):
    """取消添加不改变会话，无效文件不进入图库，混合选择只追加可解码的新图片。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    first = _write_image(tmp_path / "first.png", Qt.GlobalColor.red)
    second = _write_image(tmp_path / "second.png", Qt.GlobalColor.blue)
    invalid = tmp_path / "invalid.png"
    invalid.write_text("not an image", encoding="utf-8")
    notices = []
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
    )
    selected = []
    monkeypatch.setattr(actions.QFileDialog, "getOpenFileNames", lambda *_args: (selected, ""))
    page = ScreenshotPage([first])
    changes = QSignalSpy(page.image_count_changed)
    try:
        page._add_action.trigger()
        assert page.image_paths == (first,)
        assert page._current_path() == first
        assert changes.count() == 0 and not notices
        assert page._add_action.isEnabled()

        selected[:] = [str(invalid), str(tmp_path / "missing.png")]
        page._add_action.trigger()
        assert page.image_paths == (first,)
        assert page._current_path() == first
        assert changes.count() == 0
        assert notices[-1][1]["level"] == "warning"
        assert page._add_action.isEnabled()

        selected[:] = [second, str(invalid), first, second]
        page._add_action.trigger()
        assert page.image_paths == (first, second)
        assert page._current_path() == second
        assert page._view.count() == page._pager.count() == 2
        assert changes.count() == 1
    finally:
        page.close()


def test_screenshot_add_images_rejects_reentry_and_late_dialog_result_after_dispose(
    qt_application, tmp_path, monkeypatch,
):
    """文件对话框的嵌套事件循环不能重复打开窗口，也不能给已释放的页面回填结果。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    path = _write_image(tmp_path / "late.png", Qt.GlobalColor.green)
    page = ScreenshotPage([])
    calls = []

    def choose_images(*_args):
        calls.append(True)
        assert not page._add_action.isEnabled()
        page._add_images()
        assert calls == [True]
        page.request_dispose()
        return [path], ""

    monkeypatch.setattr(actions.QFileDialog, "getOpenFileNames", choose_images)
    try:
        page._add_action.trigger()
        assert page.is_disposed
        assert page.image_paths == ()
        assert page._view.count() == page._pager.count() == 0
        assert calls == [True]
    finally:
        page.close()


def test_borrowed_screen_tools_keep_fit_current_and_preserve_manual_zoom(
    qt_application, tmp_path,
):
    """工具高度变化只重算适应窗口模式；手动缩放和归还控件不受影响。"""
    parking = QWidget()
    tools = QWidget(parking)
    tools.setFixedHeight(100)
    image_path = tmp_path / "portrait.png"
    portrait = QPixmap(540, 960)
    portrait.fill(Qt.GlobalColor.blue)
    assert portrait.save(str(image_path))
    page = ScreenshotPage([str(image_path)])
    page.prepare_for_workspace()
    page.set_device_tools(tools, parking)
    page.activate()
    page.resize(800, 700)
    page.show()

    def image_fits_current_viewport():
        image_height = page._view.delegate.itemSize(page._view.currentIndex()).height()
        view_height = page._view.viewport().height()
        return view_height - 18 <= image_height <= view_height

    try:
        wait_for_stable_geometry(qt_application, (page, tools, page._view))
        page._reset_zoom()
        QTest.qWait(30)
        assert image_fits_current_viewport()
        original_page_size = page.size()
        original_view_height = page._view.height()
        tools.setFixedHeight(220)
        QTest.qWait(30)
        assert page._view.height() < original_view_height
        wait_until(qt_application, image_fits_current_viewport)
        assert page.size() == original_page_size
        assert page._fit_to_window

        page.zoom_in()
        manual_zoom = page._zoom_factor
        tools.setFixedHeight(80)
        page.resize(900, 800)
        wait_for_stable_geometry(qt_application, (page, tools, page._view))
        assert not page._fit_to_window
        assert page._zoom_factor == manual_zoom
        assert page.request_dispose()
        assert not page._fit_resize_timer.isActive()
        assert tools.parentWidget() is parking
        assert tools.isHidden()
    finally:
        page.close()
        page.deleteLater()
        parking.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("with_image", [False, True], ids=["empty", "loaded"])
def test_screenshot_workspace_preparation_releases_header_space_without_resetting_content(
    qt_application, tmp_path, with_image,
):
    """嵌入钩子隐藏整组重复页头，空态与有图态均把空间留给原画布。"""

    paths = [_write_image(tmp_path / "shot.png", Qt.GlobalColor.blue)] if with_image else []
    page = ScreenshotPage(paths)
    canvas = page._image_stack
    try:
        page.resize(760, 600)
        page.show()
        wait_for_stable_geometry(qt_application, (page, page.header_card, canvas))
        assert page.header_card.isVisibleTo(page)
        assert page.dialog_title.isVisibleTo(page)
        assert page.dialog_subtitle.isVisibleTo(page)
        assert page.status_badge.isVisibleTo(page)
        original_canvas_height = canvas.height()
        header_height = page.header_card.height()
        count_changes = QSignalSpy(page.image_count_changed)
        original_view = page._view

        page.prepare_for_workspace()
        page.prepare_for_workspace()
        page._apply_theme()
        wait_for_stable_geometry(qt_application, (page, canvas, page._command_bar))

        assert page.header_card.isHidden()
        assert not page.dialog_title.isVisibleTo(page)
        assert not page.dialog_subtitle.isVisibleTo(page)
        assert not page.status_badge.isVisibleTo(page)
        assert canvas.height() >= original_canvas_height + header_height
        assert page._command_bar.isVisibleTo(page)
        assert page._view is original_view
        assert page.image_paths == tuple(paths)
        assert count_changes.count() == 0
        assert page._nav_label.text() == ("1 / 1" if with_image else "0 / 0")
        assert page._copy_action.isEnabled() is with_image
    finally:
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_screenshot_workspace_entry_hides_header_and_reuses_the_result_page(qt_application):
    """真实宿主入口调用页面的嵌入钩子，往返导航不重新显示重复标题。"""

    host = WorkspaceFeatureHost("apps", "应用概览", QWidget())
    host.register_feature(
        "media", "截图结果", FluentIcon.PHOTO, lambda _key: ScreenshotPage([]),
        requires_device=False,
    )
    try:
        host.resize(760, 600)
        host.show()
        assert host.open_feature("media")
        page = host.stack.currentWidget()
        assert isinstance(page, ScreenshotPage)
        qt_application.processEvents()
        assert page.header_card.isHidden()
        assert page._empty_label.isVisibleTo(host)
        assert page._command_bar.isVisibleTo(host)

        assert host.show_overview()
        assert host.open_feature("media")
        assert host.stack.currentWidget() is page
        assert page.header_card.isHidden()
        assert not page.is_disposed
    finally:
        host.shutdown()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(host, QEvent.Type.DeferredDelete)


def test_screenshot_page_is_plain_widget_and_incrementally_appends_batches(
    qt_application,
    tmp_path,
):
    first = _write_image(tmp_path / "first.png", Qt.GlobalColor.red)
    second = _write_image(tmp_path / "second.png", Qt.GlobalColor.green)
    page = ScreenshotPage([first])
    try:
        assert isinstance(page, QWidget)
        assert not isinstance(page, QDialog)

        page.activate({"paths": [first, second]})

        assert page._image_paths == [first, second]
        assert page._current_path() == second
        assert page._nav_label.text() == "2 / 2"

        page.deactivate("navigation")
        page.activate([second])

        assert page._image_paths == [first, second]
        assert page._current_path() == second
    finally:
        page.close()


def test_screenshot_page_deletes_last_image_with_one_click_and_keeps_empty_page_open(
    qt_application,
    tmp_path,
):
    path = _write_image(tmp_path / "last.png", Qt.GlobalColor.blue)
    parent = QWidget()
    page = ScreenshotPage([path], parent=parent)
    parent.show()
    page.show()
    qt_application.processEvents()
    try:
        page._delete_action.trigger()

        assert not os.path.exists(path)
        assert page._image_paths == []
        assert page._nav_label.text() == "0 / 0"
        assert page._image_stack.currentWidget() is page._empty_label
        assert page._empty_label.text() == "No screenshot available"
        assert page._empty_label.isVisibleTo(parent)
        assert page._view.count() == page._pager.count() == 0
        assert not page._delete_action.isEnabled()
        assert not page._copy_action.isEnabled()
        assert page._add_action.isEnabled()
        assert page.isVisible()
        assert parent.isVisible()
    finally:
        parent.close()


def test_screenshot_page_lifecycle_preserves_navigation_state_until_dispose(
    qt_application,
    tmp_path,
):
    path = _write_image(tmp_path / "shot.png", Qt.GlobalColor.cyan)
    page = ScreenshotPage([path])
    try:
        page.activate()
        page.deactivate("overview")

        assert page._image_paths == [path]
        assert page.property("deactivation_reason") == "overview"
        assert page.register_shutdown_tasks(
            object(),
            owner_id="test-owner",
            task_prefix="screenshot",
        ) == ()

        assert page.request_dispose("application_shutdown") is True
        assert page.is_disposed is True
        assert page._image_paths == []
        assert page.request_dispose("application_shutdown") is True
    finally:
        page.close()


def test_screenshot_deactivation_mid_animation_aligns_current_image_before_reactivation(
    qt_application, tmp_path,
):
    """跨页动画中停用必须对齐当前截图，复归不依赖隐藏再显示来修复半页画面。"""

    paths = [
        _write_image(tmp_path / f"animation-{index}.png", Qt.GlobalColor.blue)
        for index in range(8)
    ]
    page = ScreenshotPage(paths)
    try:
        page.resize(760, 620)
        page.show()
        page.activate()
        view, pager = page._view, page._pager
        wait_for_stable_geometry(qt_application, (page, view, pager))
        view.setCurrentIndex(7)
        assert view.scrollBar.ani.state() == QAbstractAnimation.State.Running
        view.scrollBar.ani.setCurrentTime(view.scrollBar.ani.duration() // 2)
        assert not view.viewport().rect().contains(view.visualItemRect(view.item(7)))

        page.deactivate("navigation")
        assert view.scrollBar.ani.state() == QAbstractAnimation.State.Stopped
        assert pager.scrollBar.ani.state() == QAbstractAnimation.State.Stopped
        assert view.viewport().rect().adjusted(-2, -2, 2, 2).contains(
            view.visualItemRect(view.item(7))
        )
        assert pager.viewport().rect().contains(pager.visualItemRect(pager.currentItem()))
        assert page.isVisible() and view.isVisibleTo(page)
        assert page._current_path() == paths[7]

        page.activate(None)
        qt_application.processEvents()
        assert view.currentIndex() == pager.currentIndex() == 7
        assert page._current_path() == paths[7]
        assert view.viewport().rect().adjusted(-2, -2, 2, 2).contains(
            view.visualItemRect(view.item(7))
        )
        assert page.request_dispose()
        assert view.count() == pager.count() == 0
        assert view.scrollBar.ani.state() == QAbstractAnimation.State.Stopped
        assert pager.scrollBar.ani.state() == QAbstractAnimation.State.Stopped
    finally:
        page.close()


def test_screenshot_page_escape_requests_back_navigation_without_closing(
    qt_application,
):
    page = ScreenshotPage([])
    back_spy = QSignalSpy(page.back_requested)
    try:
        page.show()
        page.setFocus()
        qt_application.processEvents()

        QTest.keyClick(page, Qt.Key.Key_Escape)
        qt_application.processEvents()

        assert back_spy.count() == 1
        assert page.isVisible()
        assert page.is_disposed is False
    finally:
        page.close()


def test_screenshot_copy_notifies_without_replacing_current_image_metadata(
    qt_application, tmp_path, monkeypatch,
):
    """复制成功使用完整结果提示，底栏保留当前图信息，导航后也不恢复旧内容。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    first = _write_image(tmp_path / "first.png", Qt.GlobalColor.red)
    second = _write_image(tmp_path / "second.png", Qt.GlobalColor.blue)
    notices = []
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
        raising=False,
    )
    page = ScreenshotPage([first, second])
    try:
        page.show()
        metadata = page._info_label.text()
        page.copy_to_clipboard()

        assert qt_application.clipboard().pixmap().toImage() == QPixmap(first).toImage()
        assert page._info_label.text() == metadata
        assert page._info_label.toolTip() == metadata
        assert len(notices) == 1
        args, options = notices[0]
        assert args[0] is page
        assert args[2] == "Image copied"
        assert options["duration"] is None
        page.navigate_next()
        assert page._current_path() == second
        assert page._info_label.text() == page._info_label.toolTip()
    finally:
        page.close()


@pytest.mark.parametrize("entry", ["button", "more_menu", "context_menu"])
def test_screenshot_delete_entry_click_removes_only_current_image_once(
    qt_application, tmp_path, monkeypatch, entry,
):
    """按钮、更多和右键菜单共享一个删除动作，每次点击只删除当前文件并更新一次数量。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    paths = [
        _write_image(tmp_path / f"delete-{index}.png", color)
        for index, color in enumerate((
            Qt.GlobalColor.red, Qt.GlobalColor.green, Qt.GlobalColor.blue,
        ))
    ]
    notices = []
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
    )
    page = ScreenshotPage(paths)
    try:
        page.resize(1500 if entry == "button" else 380, 700)
        page.show()
        page._pager.setCurrentIndex(1)
        wait_for_stable_geometry(qt_application, (page, page._view, page._command_bar))
        changes = QSignalSpy(page.image_count_changed)
        assert page._current_path() == paths[1]
        if entry == "button":
            button = next(
                button for button in page._command_bar.commandButtons
                if button.action() is page._delete_action
            )
            assert button.isVisibleTo(page)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        else:
            # 先关闭再重开菜单，验证重复打开不会为同一动作重复连接删除回调。
            for opening in range(2):
                if entry == "more_menu":
                    assert page._command_bar.moreButton.isVisibleTo(page)
                    QTest.mouseClick(page._command_bar.moreButton, Qt.MouseButton.LeftButton)
                else:
                    page._view.customContextMenuRequested.emit(page._view.viewport().rect().center())
                menu = next(menu for menu in page.findChildren(RoundMenu) if menu.isVisible())
                assert page._delete_action in menu.menuActions()
                if opening == 0:
                    menu.close()
            item = next(
                menu.view.item(row) for row in range(menu.view.count())
                if menu.view.item(row).data(Qt.ItemDataRole.UserRole) is page._delete_action
            )
            menu.view.scrollToItem(item)
            qt_application.processEvents()
            target = menu.view.visualItemRect(item)
            assert menu.view.viewport().rect().contains(target.center())
            QTest.mouseClick(menu.view.viewport(), Qt.MouseButton.LeftButton, pos=target.center())

        assert not os.path.exists(paths[1])
        assert os.path.exists(paths[0]) and os.path.exists(paths[2])
        assert page.image_paths == (paths[0], paths[2])
        assert page._current_path() == paths[2]
        assert page._view.currentIndex() == page._pager.currentIndex() == 1
        assert page._view.count() == page._pager.count() == 2
        assert page._display_pixmap.toImage() == QPixmap(paths[2]).toImage()
        assert changes.count() == 1 and changes.at(0) == [2]
        assert not notices
    finally:
        page.close()


def test_screenshot_delete_error_preserves_image_and_allows_single_click_retry(
    qt_application, tmp_path, monkeypatch,
):
    """删除失败保留文件、原图和当前索引，完整错误提示后仍可单击重试。"""

    from gui.dialogs import screenshot_viewer_actions as actions
    from gui.dialogs.fluent_dialog import FluentMessageBox

    path = _write_image(tmp_path / "cannot-delete.png", Qt.GlobalColor.cyan)
    error_text = "无法删除截图：文件正在使用。\n" + str(tmp_path / ("long-name-" * 15 + ".png"))
    notices, dialogs = [], []
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        FluentMessageBox, "warning", lambda *args: dialogs.append(args),
    )

    original_remove = actions.os.remove
    attempts = []

    def fail_once_then_remove(selected_path):
        attempts.append(selected_path)
        if len(attempts) == 1:
            raise PermissionError(error_text)
        original_remove(selected_path)

    monkeypatch.setattr(actions.os, "remove", fail_once_then_remove)
    page = ScreenshotPage([path])
    try:
        page.show()
        original = page._original_pixmap.toImage()
        display = page._display_pixmap.toImage()
        changes = QSignalSpy(page.image_count_changed)
        page._delete_action.trigger()

        assert dialogs == []
        assert os.path.exists(path)
        assert page._image_paths == [path]
        assert page._current_path() == path
        assert page._view.currentIndex() == page._pager.currentIndex() == 0
        assert page._original_pixmap.toImage() == original
        assert page._display_pixmap.toImage() == display
        assert page._delete_action.isEnabled()
        assert changes.count() == 0
        assert attempts == [path]
        args, options = notices[-1]
        assert args == (page, "Delete Failed", error_text)
        assert options["level"] == "error"
        page._delete_action.trigger()
        assert attempts == [path, path]
        assert not os.path.exists(path)
        assert page.image_paths == ()
        assert changes.count() == 1 and changes.at(0) == [0]
        assert not page._delete_action.isEnabled()
        assert len(notices) == 1
    finally:
        page.close()
