"""验证导航折叠后仍绘制当前主题背景与图标。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import FluentWindow, NavigationDisplayMode

from core.exec import CommandResult, CommandRunner
from core.settings_manager import AppSettings
from gui import window_effects
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until


def _navigation_background_pixel(frame, panel_point=None):
    """取顶部空白边距，避开当前项高亮和导航按钮。"""
    point = frame.navigationInterface.panel.mapTo(frame, panel_point or QPoint(1, 5))
    image = frame.grab().toImage()
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("transition", ["resize", "menu"])
@pytest.mark.parametrize("mica", [False, True])
def test_navigation_collapse_preserves_theme_surface(
    qt_application, monkeypatch, theme_name, transition, mica
):
    """缩窗和覆盖菜单关闭后，紧凑导航必须保留当前主题与材质。"""
    settings = _MainFrameSettings()
    settings.values.update(
        window_width=1440 if transition == "resize" else 900,
        window_height=960,
        mica_enabled=mica,
    )
    adapter = _FakeScreenAdapter(_FakeScreen("navigation-test", QSize(1800, 1200)))
    BaseStyles.switch_theme(theme_name)
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    panel = frame.navigationInterface.panel
    try:
        frame.show()
        frame._on_nav_requested("apps")
        initial_mode = (
            NavigationDisplayMode.EXPAND
            if transition == "resize"
            else NavigationDisplayMode.COMPACT
        )
        wait_until(
            qt_application,
            lambda: panel.displayMode == initial_mode
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        # 消费首次 show 的延迟材质刷新，再安装离屏 DWM 替代背景。
        qt_application.processEvents()
        if frame.isMicaEffectEnabled():
            monkeypatch.setattr(frame, "_normalBackgroundColor", lambda: QColor("#315879"))
            frame.backgroundColorAni.stop()
            frame.setBackgroundColor(QColor("#315879"))
        background = _navigation_background_pixel(frame)
        assert background.alpha() == 255

        if transition == "resize":
            frame.resize(840, 640)
        else:
            frame._toggle_navigation_panel()
            wait_until(
                qt_application,
                lambda: panel.displayMode == NavigationDisplayMode.MENU
                and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
            )
            frame._toggle_navigation_panel()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )

        assert panel.width() == 48
        assert panel.parentWidget() is frame.navigationInterface
        assert panel.menuButton.isVisibleTo(frame)
        assert _navigation_background_pixel(frame) == background
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize(
    "width,font_size,theme_name", [(900, 12, "Light"), (1600, 22, "Dark")],
)
def test_navigation_animation_keeps_top_scroll_and_bottom_icon_columns_aligned(
    qt_application, width, font_size, theme_name,
):
    """逐帧验证真实导航坐标；可在独立进程设置 QT_SCALE_FACTOR 验收不同缩放。"""
    settings = _MainFrameSettings()
    settings.values.update(
        window_width=width, window_height=750, ui_font_size=font_size, mica_enabled=False,
    )
    BaseStyles.switch_theme(theme_name)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("navigation-columns", QSize(1920, 1080))),
        settings=settings,
    )
    panel = frame.navigationInterface.panel
    items = [panel.items[key].widget for key in ("homePage", "appsPage", "settingsPage")]
    visuals = [item.itemWidget for item in items]

    def assert_columns(stage):
        columns = [widget.mapTo(frame, QPoint()).x() for widget in visuals]
        assert panel.scrollArea.horizontalScrollBar().value() == 0, (stage, columns)
        assert max(columns) - min(columns) <= 2, (stage, columns)
        assert all(column >= 0 for column in columns), (stage, columns)

    try:
        frame.show()
        wait_for_stable_geometry(qt_application, (frame, panel))
        frame._on_nav_requested("apps")
        if panel.displayMode != NavigationDisplayMode.COMPACT:
            frame._toggle_navigation_panel()
            wait_until(
                qt_application,
                lambda: panel.displayMode == NavigationDisplayMode.COMPACT
                and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
            )
        for cycle in range(2):
            for direction in ("expand", "collapse"):
                panel.menuButton.click()
                assert panel.expandAni.state() == QAbstractAnimation.State.Running
                panel.expandAni.pause()
                for fraction in (0.0, 0.25, 0.5, 0.99):
                    panel.expandAni.setCurrentTime(int(panel.expandAni.duration() * fraction))
                    qt_application.processEvents()
                    assert_columns((cycle, direction, fraction))
                panel.expandAni.resume()
                wait_until(
                    qt_application,
                    lambda: panel.expandAni.state() == QAbstractAnimation.State.Stopped,
                )
                wait_for_stable_geometry(qt_application, (panel, panel.scrollWidget))
                assert_columns((cycle, direction, "finished"))
        assert panel.displayMode == NavigationDisplayMode.COMPACT
        assert panel.width() == 48
    finally:
        panel.expandAni.stop()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_navigation_animation_keeps_entry_positions_stable(
    qt_application, monkeypatch, theme_probe_frame, theme_name, mica,
):
    """固定生效材质验证 Qt 布局，顶部、中部和底部入口不能随 MENU 边框跳动。"""
    frame = theme_probe_frame(theme_name, mica, width=900)
    monkeypatch.setattr(frame, "isMicaEffectEnabled", lambda: mica)
    frame._sync_material_surface_styles()
    panel = frame.navigationInterface.panel
    items = {
        "menu": panel.menuButton,
        **{
            key: getattr(panel.items[key].widget, "itemWidget", panel.items[key].widget)
            for key in ("homePage", "devicesPage", "appsPage", "tasksPage", "settingsPage")
        },
    }

    def positions():
        return {
            key: (widget.mapTo(frame, QPoint()).toTuple(), widget.height())
            for key, widget in items.items()
        }

    try:
        wait_for_stable_geometry(qt_application, (frame, panel, panel.scrollWidget))
        assert panel.displayMode == NavigationDisplayMode.COMPACT
        initial = positions()
        for cycle in range(2):
            for direction in ("expand", "collapse"):
                panel.menuButton.click()
                panel.expandAni.pause()
                for fraction in (0.0, 0.25, 0.5, 0.99):
                    panel.expandAni.setCurrentTime(int(panel.expandAni.duration() * fraction))
                    qt_application.processEvents()
                    assert positions() == initial, (cycle, direction, fraction)
                panel.expandAni.resume()
                wait_until(
                    qt_application,
                    lambda: panel.expandAni.state() == QAbstractAnimation.State.Stopped,
                )
                wait_for_stable_geometry(qt_application, (panel, panel.scrollWidget))
                assert positions() == initial, (cycle, direction, "finished")
        assert panel.displayMode == NavigationDisplayMode.COMPACT
    finally:
        panel.expandAni.stop()


def test_navigation_collapse_keeps_reference_button_width_until_animation_finishes(qt_application):
    """参考导航在收缩结束才提交 compact，选中背景不能先骤缩成 40px。"""
    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=750, mica_enabled=False)
    frame = build_main_frame(settings=settings)
    panel = frame.navigationInterface.panel
    item = panel.items["appsPage"].widget
    try:
        frame.show()
        wait_for_stable_geometry(qt_application, (frame, panel))
        panel.menuButton.click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.MENU
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        expanded_width = item.width()
        assert expanded_width > 40
        panel.menuButton.click()
        panel.expandAni.pause()
        for fraction in (0.0, 0.5, 0.99):
            panel.expandAni.setCurrentTime(int(panel.expandAni.duration() * fraction))
            qt_application.processEvents()
            assert item.width() == expanded_width
            assert not item.isCompacted
        panel.expandAni.resume()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        assert item.isCompacted
        assert item.width() == 40
    finally:
        panel.expandAni.stop()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_wide_navigation_manual_collapse_waits_for_user_to_reopen(qt_application):
    """宽窗手动收起应保持紧凑，尾沿布局通知不能重新覆盖用户选择。"""
    settings = _MainFrameSettings()
    settings.values.update(window_width=1600, window_height=900, mica_enabled=False)
    adapter = _FakeScreenAdapter(_FakeScreen("navigation-test", QSize(1920, 1080)))
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    panel = frame.navigationInterface.panel
    try:
        frame.show()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        finished = QSignalSpy(panel.expandAni.finished)
        panel.menuButton.click()
        wait_until(qt_application, lambda: finished.count() == 1)
        # 消费动画结束后排队的布局事件，确认收起不是一帧过渡状态。
        QTest.qWait(panel.expandAni.duration() + 100)
        assert panel.displayMode == NavigationDisplayMode.COMPACT
        assert panel.width() == 48
        assert frame.width() == 1600

        panel.menuButton.click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        assert panel.width() == panel.expandWidth
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.fixture
def theme_probe_frame(qt_application, monkeypatch):
    """主题与导航探针隔离设置和设备快照，不触及真实用户配置。"""
    frames = []
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])

    def build(theme_name, mica, *, width=1320):
        settings = _MainFrameSettings()
        settings.values.update(
            theme="Light", mica_enabled=mica, window_width=width, window_height=860
        )
        monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
        BaseStyles.switch_theme("Light")
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("theme-probe", QSize(1920, 1080))),
        )
        frames.append(frame)
        frame.show()
        qt_application.processEvents()
        BaseStyles.switch_theme(theme_name)
        qt_application.processEvents()
        if frame.isMicaEffectEnabled():
            original_background = frame._normalBackgroundColor
            monkeypatch.setattr(
                frame, "_normalBackgroundColor",
                lambda: QColor("#315879") if frame.isMicaEffectEnabled() else original_background(),
            )
            frame.setBackgroundColor(QColor("#315879"))
        return frame

    yield build
    for frame in frames:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        frame.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _assert_stack_gap_matches_surface(frame, context):
    """整窗合成取顶部空白行，避开文字、控件和圆角的抗锯齿。"""
    image = frame.grab().toImage()
    scale = image.devicePixelRatio()
    expected = QColor(BaseStyles.color("WINDOW_BG"))
    if frame.isMicaEffectEnabled():
        # 离屏使用已知根背景模拟系统材质，再核对当前设计遮罩的准确合成结果。
        sample = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        sample.fill(frame.backgroundColor)
        painter = QPainter(sample)
        tint = (
            QColor(255, 255, 255, 8) if BaseStyles.resolved_theme() == "Dark"
            else QColor(242, 244, 246, 51)
        )
        painter.fillRect(sample.rect(), tint)
        painter.end()
        expected = sample.pixelColor(0, 0)
    for fraction in (0.25, 0.5, 0.75):
        point = frame.stackedWidget.mapTo(
            frame, QPoint(round(frame.stackedWidget.width() * fraction), 2)
        )
        actual = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
        assert actual == expected, (context, point, actual.name(), actual.alpha(), expected.name())


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
def test_mica_toggle_reveals_backdrop_and_restores_opaque_surfaces(
    monkeypatch, theme_probe_frame, theme_name
):
    """用可控根背景代替 DWM，验证材质没有被 Qt 的页面与导航实色遮挡。"""
    frame = theme_probe_frame(theme_name, False)

    def set_native_mica(window, enabled):
        window._isMicaEnabled = enabled
        window.setBackgroundColor(window._normalBackgroundColor())

    monkeypatch.setattr(FluentWindow, "setMicaEffectEnabled", set_native_mica)
    frame._on_nav_requested("settings")
    animation = frame.stackedWidget.view._ani
    animation.setCurrentTime(animation.duration())
    backdrop = QColor("#315879")
    frame.setMicaEffectEnabled(True)
    frame.setBackgroundColor(backdrop)

    assert frame.isMicaEffectEnabled()
    assert not frame.titleBar.autoFillBackground()
    assert not frame.navigationInterface.autoFillBackground()
    assert not frame.navigationInterface.panel.autoFillBackground()
    assert not frame._settings_page.viewport().autoFillBackground()
    assert _navigation_background_pixel(frame) == backdrop

    image = frame.grab().toImage()
    scale = image.devicePixelRatio()
    point = frame.stackedWidget.mapTo(frame, QPoint(frame.stackedWidget.width() // 2, 2))
    content_color = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
    assert content_color != QColor(BaseStyles.color("WINDOW_BG"))
    assert content_color != backdrop
    assert content_color.blue() > content_color.red()

    frame.setMicaEffectEnabled(False)
    assert not frame.isMicaEffectEnabled()
    assert frame.titleBar.autoFillBackground()
    assert frame.navigationInterface.autoFillBackground()
    assert frame.navigationInterface.panel.autoFillBackground()
    assert _navigation_background_pixel(frame) == QColor(BaseStyles.color("WINDOW_BG"))
    _assert_stack_gap_matches_surface(frame, "mica disabled")


def test_light_material_preserves_backdrop_color_instead_of_washing_it_out(
    qt_application, monkeypatch, theme_probe_frame
):
    """浅色阅读层保留至少七成底色差异，避免多层白色把云母冲淡。"""
    frame = theme_probe_frame("Light", True)
    frame._on_nav_requested("settings")
    animation = frame.stackedWidget.view._ani
    animation.setCurrentTime(animation.duration())
    sources = (QColor("#DCE5EF"), QColor("#E8E2DC"))
    samples = []
    for source in sources:
        monkeypatch.setattr(frame, "_normalBackgroundColor", lambda color=source: color)
        frame._refresh_window_chrome_theme()
        qt_application.processEvents()
        point = frame.stackedWidget.mapTo(frame, QPoint(frame.stackedWidget.width() // 2, 2))
        rendered = frame.grab().toImage()
        scale = rendered.devicePixelRatio()
        samples.append(rendered.pixelColor(round(point.x() * scale), round(point.y() * scale)))
    # 比较颜色距离而非读取实现中的透明度，检出额外覆盖的实色或重复白色层。
    source_distance = sum(
        abs(a - b) for a, b in zip(sources[0].getRgb()[:3], sources[1].getRgb()[:3])
    )
    result_distance = sum(
        abs(a - b) for a, b in zip(samples[0].getRgb()[:3], samples[1].getRgb()[:3])
    )
    assert result_distance >= source_distance * .7
    assert all(
        sample != source and sample.alpha() == 255 for sample, source in zip(samples, sources)
    )


def test_unsupported_mica_request_keeps_opaque_surfaces(monkeypatch, theme_probe_frame):
    """上游拒绝不支持的平台请求时，Qt 表面仍按实际关闭状态绘制。"""
    frame = theme_probe_frame("Light", False)
    monkeypatch.setattr(FluentWindow, "setMicaEffectEnabled", lambda _window, _enabled: None)
    frame._on_nav_requested("settings")
    animation = frame.stackedWidget.view._ani
    animation.setCurrentTime(animation.duration())

    frame.setMicaEffectEnabled(True)

    assert not frame.isMicaEffectEnabled()
    assert frame.titleBar.autoFillBackground()
    assert frame.navigationInterface.autoFillBackground()
    assert _navigation_background_pixel(frame) == QColor(BaseStyles.color("WINDOW_BG"))
    _assert_stack_gap_matches_surface(frame, "unsupported mica")


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("section", ["apps", "system"])
def test_workspace_scroll_content_preserves_the_window_material(
    qt_application, theme_probe_frame, theme_name, section
):
    """实际工作区内层滚动留白也必须透出内容遮罩，不能只验证外层栈边缘。"""
    frame = theme_probe_frame(theme_name, False)
    frame._on_nav_requested(section)
    animation = frame.stackedWidget.view._ani
    animation.setCurrentTime(animation.duration())
    qt_application.processEvents()
    host = frame._workspace_feature_hosts[section]
    wrapper = host.overview.body.widget()

    for mica in (False, True, False):
        frame.setMicaEffectEnabled(mica)
        if frame.isMicaEffectEnabled():
            frame.setBackgroundColor(QColor("#315879"))
        image = frame.grab().toImage()
        scale = image.devicePixelRatio()

        def sample(widget, point):
            mapped = widget.mapTo(frame, point)
            return image.pixelColor(round(mapped.x() * scale), round(mapped.y() * scale))

        expected = sample(frame.stackedWidget, QPoint(frame.stackedWidget.width() // 2, 2))
        assert sample(host.stack, QPoint(2, 2)) == expected
        assert sample(wrapper, QPoint(2, 2)) == expected


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
def test_all_navigation_pages_share_material_without_covering_reading_controls(
    qt_application, monkeypatch, theme_probe_frame, theme_name
):
    """审计全部主入口和实际懒页的布局留白，设备及命令由隔离替身提供。"""
    monkeypatch.setattr(CommandRunner, "run", lambda *_args, **_kwargs: CommandResult(True, ""))
    frame = theme_probe_frame(theme_name, True)
    frame._on_devices_updated(["material-probe-device"])
    frame.left_panel._devices_tab.set_selected_devices(["material-probe-device"])
    checked = []
    for key in frame._navigation_labels:
        frame.navigationInterface.widget(key).click()
        animation = frame.stackedWidget.view._ani
        if animation is not None:
            animation.setCurrentTime(animation.duration())
        qt_application.processEvents()
        page = frame.stackedWidget.currentWidget()
        surfaces = []
        bar = frame._global_device_bar
        if bar.isVisibleTo(frame):
            surfaces.append((bar, QPoint(bar.width() // 2, bar.height() - 4)))
        for host in frame._workspace_feature_hosts.values():
            if not host.isVisibleTo(frame):
                continue
            current = host.stack.currentWidget()
            body = getattr(current, "body", None)
            if callable(getattr(body, "widget", None)):
                wrapper = body.widget()
                surfaces.append((wrapper.layout().itemAt(0).widget(), QPoint(2, 2)))
        for name in ("appManagerMasterPanel", "performanceConfig"):
            surface = page.findChild(QWidget, name)
            if surface is not None and surface.isVisibleTo(frame):
                point = QPoint(2, 2)
                if name == "performanceConfig":
                    # 两卡布局的 (2, 2) 落在 headerView 圆角，必须取实际卡片间距。
                    layout = surface.layout()
                    first = layout.itemAt(0).widget().geometry()
                    second = layout.itemAt(1).widget().geometry()
                    if first.right() < second.left():
                        point = QPoint((first.right() + second.left()) // 2, first.center().y())
                    else:
                        assert first.bottom() < second.top()
                        point = QPoint(first.center().x(), (first.bottom() + second.top()) // 2)
                    assert surface.rect().contains(point)
                    assert surface.childAt(point) is None
                surfaces.append((surface, point))
        if key == "tasksPage":
            # 页面已铺到材质面的左上角，避开该处有意保留的 10px 圆角。
            surfaces.append((frame._task_page._scroll.widget(), QPoint(2, 20)))
        image = frame.grab().toImage()
        scale = image.devicePixelRatio()

        def sample(widget, point):
            mapped = widget.mapTo(frame, point)
            return image.pixelColor(round(mapped.x() * scale), round(mapped.y() * scale))

        expected = sample(frame._content_surface, QPoint(frame._content_surface.width() - 3, 20))
        for surface, point in surfaces:
            assert sample(surface, point) == expected, (
                key, surface.objectName(), surface.childAt(point),
            )
        checked.append(key)
    assert len(checked) == 12


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_home_scroll_blank_uses_the_shared_material(theme_probe_frame, theme_name, mica):
    """首页原生滚动区的 Base 画刷不能覆盖功能区之间的材质留白。"""
    frame = theme_probe_frame(theme_name, mica)
    view = frame._home_page.widget()
    tools = frame._home_page.tool_cards["app_mgr"].parentWidget()
    assert tools is not None and tools.isVisibleTo(frame)
    expected = QColor(BaseStyles.color("WINDOW_BG"))
    if frame.isMicaEffectEnabled():
        composite = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        composite.fill(frame.backgroundColor)
        painter = QPainter(composite)
        painter.fillRect(
            composite.rect(),
            QColor(255, 255, 255, 8) if theme_name == "Dark" else QColor(242, 244, 246, 51),
        )
        painter.end()
        expected = composite.pixelColor(0, 0)
    # 快捷卡片现在属于横幅；材质探针仍采样横幅与下方分区之间的真实空白。
    banner_bottom = frame._home_page.banner.mapTo(
        view, QPoint(0, frame._home_page.banner.height()),
    ).y()
    gap = QPoint(2, banner_bottom + 3)
    assert view.childAt(gap) is None
    point = view.mapTo(frame, gap)
    image = frame.grab().toImage()
    scale = image.devicePixelRatio()
    assert image.pixelColor(round(point.x() * scale), round(point.y() * scale)) == expected


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
def test_shared_content_keeps_round_corner_when_material_changes(
    qt_application, monkeypatch, theme_probe_frame, theme_name,
):
    """内容壳的圆角不随云母开关改变；只有底色合成与边框跟随材质。"""
    frame = theme_probe_frame(theme_name, True)
    backdrop = QColor("#315879")
    monkeypatch.setattr(frame, "_normalBackgroundColor", lambda: backdrop)
    frame._on_nav_requested("settings")
    animation = frame.stackedWidget.view._ani
    animation.setCurrentTime(animation.duration())
    for enabled in (True, False, True):
        frame.setMicaEffectEnabled(enabled)
        # 原生分数缩放会触发导航重新布局，先等覆盖内容角的展开动画结束。
        wait_until(
            qt_application,
            lambda: frame.navigationInterface.panel.expandAni.state()
            == QAbstractAnimation.State.Stopped
            and frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped,
        )
        wait_for_stable_geometry(qt_application, (frame, frame._content_surface))
        frame.backgroundColorAni.stop()
        frame.setBackgroundColor(backdrop)
        qt_application.processEvents()
        image = frame.grab().toImage()
        scale = image.devicePixelRatio()
        surface = frame._content_surface

        def sample(x, y):
            point = surface.mapTo(frame, QPoint(x, y))
            return image.pixelColor(round(point.x() * scale), round(point.y() * scale))

        assert sample(0, 0) == backdrop
        if frame.isMicaEffectEnabled():
            assert sample(20, 0) != sample(20, 3)
            assert sample(0, 20) != sample(3, 20)
            assert sample(20, 3) != frame.backgroundColor
        else:
            assert sample(20, 0) == sample(20, 3) == QColor(BaseStyles.color("WINDOW_BG"))


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
def test_home_corner_mask_is_stable_across_mica_changes_and_navigation(
    qt_application, theme_probe_frame, theme_name,
):
    """实际云母开关、切页和尺寸变化不能把首页固定圆角恢复成直角。"""
    frame = theme_probe_frame(theme_name, True, width=900)
    home = frame._home_page
    viewport = home.viewport()
    for width in (900, 1120):
        frame.resize(width, 600)
        for enabled in (True, False, True):
            frame._on_nav_requested("settings")
            frame.setMicaEffectEnabled(enabled)
            frame._on_nav_requested("home")
            wait_until(
                qt_application,
                lambda: frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
                and frame.navigationInterface.panel.expandAni.state()
                == QAbstractAnimation.State.Stopped,
            )
            wait_for_stable_geometry(qt_application, (frame, home, viewport, home.banner))
            mask = viewport.mask()
            assert not mask.isEmpty()
            assert mask.boundingRect() == viewport.rect()
            assert not mask.contains(QPoint(0, 0))
            assert mask.contains(QPoint(10, 0))
            for scroll in (0, 50, home.verticalScrollBar().maximum()):
                home.verticalScrollBar().setValue(scroll)
                qt_application.processEvents()
                assert viewport.mask() == mask


@pytest.mark.parametrize("build, attribute, off_value", [(22000, 1029, 0), (26200, 38, 1)])
def test_native_backdrop_switch_explicitly_clears_mica(monkeypatch, build, attribute, off_value):
    """关闭请求必须清除系统 backdrop，不能只移除上游的 accent policy。"""
    requests = []
    monkeypatch.setattr(window_effects, "is_mica_supported", lambda: True)
    monkeypatch.setattr(
        window_effects.sys, "getwindowsversion", lambda: SimpleNamespace(build=build),
    )
    monkeypatch.setattr(
        window_effects, "set_dwm_attribute",
        lambda hwnd, key, value: requests.append((hwnd, key, value)) or True,
    )
    assert window_effects.sync_mica_backdrop(123, True)
    assert window_effects.sync_mica_backdrop(123, False)
    assert requests == [(123, attribute, 1 if build == 22000 else 2), (123, attribute, off_value)]


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
def test_native_palette_event_preserves_mica_theme(theme_probe_frame, theme_name):
    """Qt 的原生调色板事件处理完毕后，无边框窗口的云母仍遵循应用主题。"""
    if QApplication.platformName() != "windows" or not window_effects.is_mica_supported():
        pytest.skip("需要 Windows 11 原生窗口验证 DWM 属性")
    import ctypes
    from ctypes import wintypes

    frame = theme_probe_frame(theme_name, True)
    assert frame.isMicaEffectEnabled()
    QTest.qWait(160)
    getter = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
    getter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    getter.restype = ctypes.c_long

    QCoreApplication.sendEvent(frame.windowHandle(), QEvent(QEvent.Type.ApplicationPaletteChange))
    QTest.qWait(20)

    dark = ctypes.c_int(-1)
    assert getter(int(frame.winId()), 20, ctypes.byref(dark), ctypes.sizeof(dark)) == 0
    assert dark.value == int(theme_name == "Dark")
    modern_backdrop = window_effects.sys.getwindowsversion().build >= 22523
    attribute = 38 if modern_backdrop else 1029
    backdrop = ctypes.c_int(-1)
    assert getter(
        int(frame.winId()), attribute, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
    ) == 0
    assert backdrop.value == (2 if modern_backdrop else 1)
    frame.setMicaEffectEnabled(False)
    assert getter(
        int(frame.winId()), attribute, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
    ) == 0
    assert backdrop.value == (1 if modern_backdrop else 0)
    assert getter(int(frame.winId()), 20, ctypes.byref(dark), ctypes.sizeof(dark)) == 0
    assert dark.value == int(theme_name == "Dark")


@pytest.mark.parametrize("state", ["closing", "unbound"])
def test_native_palette_sync_stops_at_window_cleanup(monkeypatch, theme_probe_frame, state):
    """关闭或解除窗口绑定后，晚到的原生事件不能再修改窗口效果。"""
    from gui import main_frame

    frame = theme_probe_frame("Dark", True)
    QTest.qWait(160)
    handle = frame.windowHandle()
    updates = []
    monkeypatch.setattr(main_frame, "apply_dark_title_bar", updates.append)
    # 重复显示/绑定不应形成多个主题监听。
    frame._bind_window_screen()
    frame._bind_window_screen()
    QCoreApplication.sendEvent(handle, QEvent(QEvent.Type.ApplicationPaletteChange))
    assert updates == [frame]

    if state == "closing":
        frame._closing = True
    else:
        frame._unbind_window_screen()
    QCoreApplication.sendEvent(handle, QEvent(QEvent.Type.ApplicationPaletteChange))
    assert updates == [frame]


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_route_animation_and_device_bar_visibility_keep_same_theme_surface(
    qt_application, theme_probe_frame, theme_name, mica
):
    frame = theme_probe_frame(theme_name, mica)
    for key in (
        "appsPage", "appManagerPage", "filesPage", "devicesPage", "settingsPage", "systemPage"
    ):
        previous = frame.stackedWidget.currentWidget()
        frame.navigationInterface.widget(key).click()
        assert frame._global_device_bar.isVisible() == (key not in {"devicesPage", "settingsPage"})
        assert frame.stackedWidget.isAnimationEnabled()
        animation = frame.stackedWidget.view._ani
        if frame.stackedWidget.currentWidget() is not previous:
            assert animation.state() == QAbstractAnimation.State.Running
            for time in (0, 30, 120):
                animation.setCurrentTime(time)
                assert frame.stackedWidget.currentWidget().y() > 0
                _assert_stack_gap_matches_surface(frame, (key, time))
            animation.setCurrentTime(animation.duration())
        _assert_stack_gap_matches_surface(frame, (key, "immediate"))
        qt_application.processEvents()
        _assert_stack_gap_matches_surface(frame, (key, "layout"))


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_rapid_route_replacement_keeps_animated_gap_in_current_theme(
    theme_probe_frame, theme_name, mica
):
    frame = theme_probe_frame(theme_name, mica)
    for key in ("appsPage", "settingsPage", "systemPage", "filesPage", "appsPage"):
        frame.navigationInterface.widget(key).click()
        animation = frame.stackedWidget.view._ani
        assert frame.stackedWidget.isAnimationEnabled()
        assert animation.state() == QAbstractAnimation.State.Running
        animation.setCurrentTime(30)
        _assert_stack_gap_matches_surface(frame, key)


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_menu_collapse_style_reset_frame_preserves_current_material(
    qt_application, monkeypatch, theme_probe_frame, theme_name, mica
):
    frame = theme_probe_frame(theme_name, mica, width=900)
    panel = frame.navigationInterface.panel
    frame._toggle_navigation_panel()
    wait_until(
        qt_application,
        lambda: panel.displayMode == NavigationDisplayMode.MENU
        and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
    )
    menu_point = QPoint(2, 20)
    menu_background = _navigation_background_pixel(frame, menu_point)
    captured = []
    original_set_style = panel.setStyle

    def capture_style_reset(style):
        original_set_style(style)
        captured.append(_navigation_background_pixel(frame, QPoint(1, 300)))

    monkeypatch.setattr(panel, "setStyle", capture_style_reset)
    frame._toggle_navigation_panel()
    assert panel.expandAni.state() == QAbstractAnimation.State.Running
    for time in (0, panel.expandAni.duration() // 2):
        panel.expandAni.setCurrentTime(time)
        assert panel.displayMode == NavigationDisplayMode.MENU
        assert panel.expandAni.state() == QAbstractAnimation.State.Running
        assert _navigation_background_pixel(frame, menu_point) == menu_background
    wait_until(
        qt_application,
        lambda: panel.displayMode == NavigationDisplayMode.COMPACT
        and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
    )
    assert captured, "必须采到上游收起尾沿 setStyle 后、主窗口恢复前的实际绘制"
    expected = (
        frame.backgroundColor
        if frame.isMicaEffectEnabled()
        else QColor(BaseStyles.color("WINDOW_BG"))
    )
    assert all(color == expected for color in captured), [
        (color.name(), color.alpha()) for color in captured
    ]
    assert _navigation_background_pixel(frame) == expected
