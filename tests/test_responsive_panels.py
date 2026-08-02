"""验证 Apps、System 和 Remote 面板在断点切换时仅重排现有控件。"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QFont

from gui.panels.app_panel import AppPanel
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel import SidePanel
from gui.panels.system_panel import SystemPanel


def _side_panel() -> SimpleNamespace:
    """构造面板布局测试需要的最小 SidePanel 接口。"""

    return SimpleNamespace(
        _font_sm=QFont("Arial", 10),
        _font_base=QFont("Arial", 10),
        _font_mono=QFont("Courier New", 10),
        _font_tab=QFont("Arial", 10),
        _package_history=[],
        _apply_completer_style=lambda _completer: None,
        selected_devices=[],
        signals=SimpleNamespace(),
    )


def _responsive_spec(panel, widget):
    """返回包含指定控件的响应式行定义。"""

    return next(spec for spec in panel._responsive_rows if widget in spec["widgets"])


def _grid_position(layout, widget) -> tuple[int, int]:
    """读取控件在网格中的行列位置。"""

    index = layout.indexOf(widget)
    assert index >= 0
    row, column, _row_span, _column_span = layout.getItemPosition(index)
    return row, column


def test_app_panel_reflows_controls_without_recreating_or_disconnecting_them():
    settings = Mock()
    settings.get.return_value = {}
    panel = AppPanel(_side_panel())

    with patch("core.settings_manager.AppSettings.instance", return_value=settings):
        widget = panel.build_ui()

    try:
        capture_row = _responsive_spec(panel, panel.btn_screenshot)
        percentage_row = _responsive_spec(panel, panel._monkey_pct_combos["touch"])
        original_controls = tuple(capture_row["widgets"])
        clicks = []
        panel.btn_screenshot.clicked.connect(lambda: clicks.append("screenshot"))

        panel.apply_responsive_width(300)
        assert capture_row["layout"].property("responsiveColumnCount") == 2
        assert _grid_position(capture_row["layout"], panel.btn_stop_record) == (1, 1)
        assert percentage_row["layout"].property("responsiveColumnCount") == 2

        panel.apply_responsive_width(500)
        assert percentage_row["layout"].property("responsiveColumnCount") == 4

        panel.apply_responsive_width(700)
        assert capture_row["layout"].property("responsiveColumnCount") == 4
        assert percentage_row["layout"].property("responsiveColumnCount") == 6
        assert tuple(capture_row["widgets"]) == original_controls

        panel.btn_screenshot.click()
        assert clicks == ["screenshot"]
    finally:
        widget.close()
        panel.close()


def test_system_panel_reflows_input_and_action_rows_without_recreating_controls():
    panel = SystemPanel(_side_panel())
    widget = panel.build_ui()

    try:
        shell_row = _responsive_spec(panel, panel.shell_cmd_input)
        reboot_row = _responsive_spec(panel, panel.reboot_mode_combo)
        original_shell_controls = tuple(shell_row["widgets"])
        clicks = []
        panel.btn_shell_run.clicked.connect(lambda: clicks.append("run"))

        panel.apply_responsive_width(300)
        assert shell_row["layout"].property("responsiveColumnCount") == 1
        assert _grid_position(shell_row["layout"], panel.btn_shell_run) == (1, 0)
        assert reboot_row["layout"].property("responsiveColumnCount") == 2

        panel.apply_responsive_width(700)
        assert shell_row["layout"].property("responsiveColumnCount") == 2
        assert reboot_row["layout"].property("responsiveColumnCount") == 4
        assert tuple(shell_row["widgets"]) == original_shell_controls

        panel.btn_shell_run.click()
        assert clicks == ["run"]
    finally:
        widget.close()
        panel.close()


def test_remote_panel_reflows_parameter_and_control_grids_without_recreating_buttons():
    settings = Mock()
    settings.get.side_effect = lambda _key, default=None: default
    settings.save_directory = "."
    adb = SimpleNamespace(path="adb")

    with (
        patch("gui.panels.remote_panel.AppSettings.instance", return_value=settings),
        patch("gui.panels.remote_panel.ADBBridge", return_value=adb),
        patch("gui.panels.remote_panel.ScrcpyService", return_value=Mock()),
        patch("gui.panels.remote_panel.RemoteControlService", return_value=Mock()),
        patch("gui.panels.remote_panel.RemoteInputEngine", return_value=Mock()),
    ):
        panel = RemotePanel(_side_panel())
        widget = panel.build_ui()

    try:
        parameter_row = _responsive_spec(panel, panel.maxsize)
        original_key_buttons = tuple(panel._remote_primary_key_buttons)
        original_media_buttons = tuple(panel._remote_media_buttons)
        original_action_buttons = tuple(panel._remote_action_buttons)
        panel._send_keyevent = Mock()
        panel._send_remote_action = Mock()

        panel.apply_responsive_width(300)
        assert parameter_row["layout"].property("responsiveColumnCount") == 2
        assert panel._remote_key_layout.property("responsiveColumnCount") == 3
        assert panel._remote_media_layout.property("responsiveColumnCount") == 3
        assert panel._remote_action_layout.property("responsiveColumnCount") == 2
        assert _grid_position(panel._remote_key_layout, original_key_buttons[-1]) == (3, 0)

        panel.apply_responsive_width(500)
        assert parameter_row["layout"].property("responsiveColumnCount") == 4
        assert panel._remote_key_layout.property("responsiveColumnCount") == 5
        assert panel._remote_action_layout.property("responsiveColumnCount") == 2

        panel.apply_responsive_width(700)
        assert parameter_row["layout"].property("responsiveColumnCount") == 6
        assert panel._remote_key_layout.property("responsiveColumnCount") == 5
        assert panel._remote_media_layout.property("responsiveColumnCount") == 5
        assert panel._remote_action_layout.property("responsiveColumnCount") == 4
        assert tuple(panel._remote_primary_key_buttons) == original_key_buttons
        assert tuple(panel._remote_media_buttons) == original_media_buttons
        assert tuple(panel._remote_action_buttons) == original_action_buttons

        original_key_buttons[0].click()
        original_action_buttons[0].click()
        panel._send_keyevent.assert_called_once_with("HOME")
        panel._send_remote_action.assert_called_once_with("swipe_up")
    finally:
        panel.shutdown()
        widget.close()
        panel.close()


def test_side_panel_uses_viewport_width_as_right_panel_source(qt_application):
    panel = SidePanel()
    viewport = panel._tab_scroll_areas[0].viewport()
    viewport.resize(419, 300)
    panel._devices_tab.apply_responsive_width = Mock()
    panel._apps_tab.apply_responsive_width = Mock()
    try:
        panel.apply_responsive_widths(330, 700)

        panel._devices_tab.apply_responsive_width.assert_called_once_with(330)
        panel._apps_tab.apply_responsive_width.assert_called_once_with(viewport.width())
        assert panel._apps_tab.apply_responsive_width.call_args.args[0] != 700
    finally:
        panel.close()
