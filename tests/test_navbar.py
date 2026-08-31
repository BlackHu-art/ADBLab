"""验证 NavBar 的折叠切换、导航信号与宽度预算契约（P1-A）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from gui.main_frame_shell import MainFrameShell
from gui.widgets.fluent.nav import NavBar

# ── NavBar：条目 / 导航信号 ─────────────────────────────────────────────


def test_navbar_default_entries_are_wide_without_tooltip(qt_application):
    """默认四条稳定键，宽态为图标 + 文字且不携带 tooltip。"""

    nav = NavBar()
    assert nav.keys() == ("devices", "tasks", "logs", "settings")
    assert [button.text() for button in nav.buttons()] == [
        "Devices",
        "Tasks",
        "Logs",
        "Settings",
    ]
    assert nav.is_collapsed() is False
    for button in nav.buttons():
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert button.toolTip() == ""


def test_navbar_click_emits_navigate_requested_with_key(qt_application):
    """点击条目只发出一次 navigate_requested，参数为对应业务键。"""

    nav = NavBar()
    requested = []
    nav.navigate_requested.connect(requested.append)
    nav.buttons()[1].click()

    assert requested == ["tasks"]
    assert nav.current_key() == "tasks"


def test_navbar_set_current_key_does_not_emit_navigate(qt_application):
    """程序化选中只更新高亮，不发出导航信号；set_page 为兼容别名。"""

    nav = NavBar()
    requested = []
    nav.navigate_requested.connect(requested.append)

    nav.set_current_key("logs")
    assert nav.current_key() == "logs"
    assert nav.buttons()[2].isChecked()

    nav.set_page("settings")
    assert nav.current_key() == "settings"
    assert nav.buttons()[3].isChecked()

    assert requested == []


# ── NavBar：折叠切换 / 宽度预算 ─────────────────────────────────────────


def test_navbar_collapsed_changed_emits_once_per_transition(qt_application):
    """折叠状态每变化一次发出一次 collapsed_changed，重复设置不重复发出。"""

    nav = NavBar()
    states = []
    nav.collapsed_changed.connect(states.append)

    nav.set_collapsed(True)
    assert states == [True]
    assert nav.is_collapsed() is True

    nav.set_collapsed(True)
    assert states == [True]

    nav.set_collapsed(False)
    assert states == [True, False]
    assert nav.is_collapsed() is False


def test_navbar_collapsed_uses_icon_only_with_tooltip(qt_application):
    """折叠态为纯图标 + tooltip；展开态恢复图标 + 文字且清空 tooltip。"""

    nav = NavBar()
    nav.set_collapsed(True)
    for button in nav.buttons():
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert button.toolTip() != ""

    nav.set_collapsed(False)
    for button in nav.buttons():
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert button.toolTip() == ""


def test_navbar_width_budget_collapses_below_threshold(qt_application):
    """宽度预算在阈值两侧切换折叠态；apply_width_budget 为兼容别名。"""

    nav = NavBar()
    nav.set_width_budget(NavBar.COLLAPSE_WIDTH_BUDGET - 1)
    assert nav.is_collapsed() is True

    nav.set_width_budget(NavBar.COLLAPSE_WIDTH_BUDGET)
    assert nav.is_collapsed() is False

    nav.apply_width_budget(NavBar.COLLAPSE_WIDTH_BUDGET - 1)
    assert nav.is_collapsed() is True


# ── MainFrameShell：页面路由 / 导航回调 ─────────────────────────────────


def test_shell_routes_pages_and_settings_callback(qt_application):
    """set_page 切换页面栈，settings 走导航回调且不改变当前页面。"""

    shell = MainFrameShell()
    page_a = QLabel("A")
    page_b = QLabel("B")
    shell.register_page("devices", page_a)
    shell.register_page("tasks", page_b)

    shell.set_page("tasks")
    assert shell.current_page == "tasks"

    opened = []
    shell.register_nav_callback("settings", lambda: opened.append(True))
    shell.set_page("settings")
    assert opened == [True]
    assert shell.current_page == "tasks"
