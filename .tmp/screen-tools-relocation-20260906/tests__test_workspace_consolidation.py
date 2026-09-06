"""验证工作区表单合并后旧入口、控件归属与批量动作仍然可用。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QWidget
from qfluentwidgets import HeaderCardWidget

from gui.panels.app_panel import AppPanel
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.system_panel import SystemPanel
from gui.widgets.category_stack import AdaptiveCategoryStack


@pytest.fixture
def panel_factory(monkeypatch):
    settings = Mock()
    settings.get.side_effect = lambda _key, default=None: default
    settings.save_directory = "."
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: settings)
    for name in ("ADBBridge", "ScrcpyService", "RemoteControlService", "RemoteInputEngine"):
        monkeypatch.setattr(f"gui.panels.remote_panel.{name}", Mock())
    created = []

    def build(panel_type):
        owner = SimpleNamespace(
            selected_devices=[],
            _package_history=[],
            _font_sm=QFont("Segoe UI", 12),
            _font_base=QFont("Segoe UI", 12),
            _font_mono=QFont("Consolas", 12),
            _apply_completer_style=lambda _completer: None,
            signals=SidePanelSignals(),
        )
        panel = panel_type(owner)
        root = panel.build_ui()
        created.append((panel, root))
        return owner, panel, root

    yield build
    for panel, root in created:
        if isinstance(panel, RemotePanel):
            panel._remote_executor.shutdown(wait=True)
        root.deleteLater()
        panel.deleteLater()


def test_category_aliases_share_pages_without_extra_navigation_or_notifications(qt_application):
    stack = AdaptiveCategoryStack("merged")
    content = QWidget()
    daily = stack.add_category("daily", "应用操作", (content,))
    stack.add_category("monkey", "Monkey")
    parent_before = content.parentWidget()
    stack.add_alias("packages", "daily")
    stack.add_alias("diagnostics", "daily")

    assert stack.category_keys == ("daily", "monkey")
    assert stack.stack.count() == stack.combo.count() == len(stack.pivot.items) == 2
    assert stack.page("packages") is stack.page("diagnostics") is daily
    assert content.parentWidget() is parent_before is daily

    stack.set_current("monkey")
    changes = QSignalSpy(stack.current_changed)
    assert stack.set_current("packages")
    assert stack.current_key == "daily"
    assert stack.stack.currentWidget() is daily
    assert stack.combo.currentData() == "daily"
    assert stack.pivot.currentRouteKey() == "merged:daily"
    assert stack.set_current("diagnostics")
    assert changes.count() == 1
    assert changes.at(0) == ["daily"]
    assert not stack.set_current("missing")


@pytest.mark.parametrize(
    ("alias", "target"),
    (("", "daily"), ("daily", "daily"), ("legacy", "daily"), ("new", "missing"), ("new", "legacy")),
)
def test_category_alias_rejects_ambiguous_or_missing_targets(qt_application, alias, target):
    stack = AdaptiveCategoryStack("merged")
    stack.add_category("daily", "应用操作")
    stack.add_alias("legacy", "daily")
    with pytest.raises(ValueError):
        stack.add_alias(alias, target)
    with pytest.raises(ValueError):
        stack.add_category("legacy", "重复入口")
    assert stack.category_keys == ("daily",)
    assert stack.page("legacy") is stack.page("daily")


@pytest.mark.parametrize(
    ("panel_type", "expected", "aliases"),
    (
        (
            AppPanel,
            {
                "daily": ("应用包管理", "文本与屏幕", "Monkey", "报告与日志", "性能诊断"),
            },
            {"packages": "daily", "diagnostics": "daily", "monkey": "daily"},
        ),
        (
            SystemPanel,
            {
                "commands": (
                    "Shell 命令", "广播与 Intent", "Android 设置",
                    "重启与模式",
                    "端口转发",
                    "系统服务开关 (svc)",
                    "电池与快捷设置",
                    "输入法与模拟器控制",
                    "系统工具",
                ),
            },
            {"settings": "commands", "device": "commands", "connectivity": "commands"},
        ),
        (
            RemotePanel,
            {"mirroring": ("屏幕镜像", "远程按键与手势")},
            {"control": "mirroring"},
        ),
    ),
)
def test_merged_panels_keep_every_card_and_responsive_control(
    qt_application, panel_factory, panel_type, expected, aliases
):
    _owner, panel, root = panel_factory(panel_type)
    stack = panel.category_stack
    assert stack.category_keys == tuple(expected)
    cards = root.findChildren(HeaderCardWidget)
    assert len(cards) == sum(len(titles) for titles in expected.values())
    controls = tuple(widget for binding in panel._responsive_rows for widget in binding.widgets())
    ownership = {widget: widget.parentWidget() for widget in controls}
    binding_ids = tuple(id(binding) for binding in panel._responsive_rows)
    root.resize(1000, 900)
    root.show()

    for key, titles in expected.items():
        page = stack.page(key)
        assert page is not None
        page_layout = page.layout()
        assert page_layout is not None
        page_cards = tuple(
            page_layout.itemAt(index).widget() for index in range(page_layout.count())
        )
        assert tuple(card.headerLabel.text() for card in page_cards) == titles
        assert all(card.parentWidget() is page for card in page_cards)
        assert stack.set_current(key)
        qt_application.processEvents()
        assert all(card.isVisibleTo(root) for card in page_cards)

    for alias, canonical in aliases.items():
        assert stack.set_current(alias)
        assert stack.current_key == canonical
        assert stack.page(alias) is stack.page(canonical)
    assert tuple(id(binding) for binding in panel._responsive_rows) == binding_ids
    assert tuple(
        widget for binding in panel._responsive_rows for widget in binding.widgets()
    ) == controls
    assert all(widget.parentWidget() is parent for widget, parent in ownership.items())
    assert all(
        sum(stack.page(key).isAncestorOf(widget) for key in expected) == 1 for widget in controls
    )
    if isinstance(panel, RemotePanel):
        assert panel._form_controller.parent() is root


def test_merged_apps_batch_install_uses_selected_devices_without_package(
    qt_application, panel_factory
):
    owner, apps, _root = panel_factory(AppPanel)
    apps.connect_signals()
    requests = QSignalSpy(owner.signals.batch_install_requested)
    apps.category_stack.set_current("packages")
    assert apps.category_stack.page("daily").isAncestorOf(apps.btn_batch_install)
    assert not apps.btn_batch_install.isEnabled()

    owner.selected_devices = ["device-a", "device-b"]
    apps._update_action_states()
    assert not apps.package_text
    assert apps.btn_batch_install.isEnabled()
    apps.btn_batch_install.click()
    assert requests.count() == 1
    assert requests.at(0) == [["device-a", "device-b"]]

    owner.selected_devices = []
    apps._update_action_states()
    apps.btn_batch_install.click()
    assert requests.count() == 1


def test_merged_system_keeps_reboot_mode_action_for_batch_targets(qt_application, panel_factory):
    owner, system, _root = panel_factory(SystemPanel)
    system.connect_signals()
    owner.selected_devices = ["device-a", "device-b"]
    system._update_action_states()
    system.category_stack.set_current("device")
    assert system.category_stack.page("connectivity").isAncestorOf(system.btn_reboot_mode)
    requests = QSignalSpy(owner.signals.reboot_mode_requested)
    system.reboot_mode_combo.setCurrentText("Recovery")
    system.btn_reboot_mode.click()
    assert requests.count() == 1
    assert requests.at(0) == [["device-a", "device-b"], "recovery"]
