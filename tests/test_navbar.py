"""验证主界面直接使用 qfluentwidgets 导航与卡片组件。"""

from __future__ import annotations

from qfluentwidgets import NavigationInterface

from gui.styles.icon_loader import get_themed_icon


def _navigation() -> tuple[NavigationInterface, list[str]]:
    requested: list[str] = []
    nav = NavigationInterface()
    for key, icon, label in (
        ("devices", "devices.svg", "Devices"),
        ("tasks", "list-checks.svg", "Tasks"),
        ("logs", "log.svg", "Logs"),
        ("settings", "gear.svg", "Settings"),
    ):
        nav.addItem(
            key,
            get_themed_icon(icon),
            label,
            onClick=lambda _checked=False, k=key: requested.append(k),
        )
    nav.setCurrentItem("devices")
    return nav, requested


def test_navigation_interface_exposes_stable_routes(qt_application):
    nav, _requested = _navigation()

    assert all(nav.widget(key) is not None for key in ("devices", "tasks", "logs", "settings"))
    assert nav.widget("devices").isSelected


def test_navigation_click_routes_once(qt_application):
    nav, requested = _navigation()

    nav.widget("tasks").click()

    assert requested == ["tasks"]
    assert nav.widget("tasks").isSelected


def test_navigation_width_configuration_uses_reference_api(qt_application):
    nav, _requested = _navigation()
    nav.setExpandWidth(160)
    nav.setMinimumExpandWidth(720)

    assert nav.panel.expandWidth == 160
    assert nav.panel.minimumExpandWidth == 720
