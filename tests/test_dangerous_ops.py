from types import SimpleNamespace

from PySide6.QtWidgets import QMessageBox

from core.dangerous_ops import DangerousOperationPolicy
from gui.dialogs.app_manager import AppManagerDialog
from gui.main_frame import MainFrame


def test_dangerous_policy_requires_confirmation_without_exposing_values():
    decision = DangerousOperationPolicy().evaluate(
        "run_shell_command",
        confirmation_enabled=True,
        target_count=3,
    )

    assert decision.requires_confirmation is True
    assert decision.operation.risk == "high"
    assert "3 targets" in decision.message
    assert "shell command" in decision.message


def test_unknown_operation_is_not_intercepted():
    decision = DangerousOperationPolicy().evaluate(
        "take_screenshot",
        confirmation_enabled=True,
    )

    assert decision.operation is None
    assert decision.requires_confirmation is False


def test_disable_for_user_keeps_dangerous_operation_confirmation():
    decision = DangerousOperationPolicy().evaluate(
        "disable_app_for_user",
        confirmation_enabled=True,
        target_count=2,
    )

    assert decision.requires_confirmation is True
    assert decision.operation.key == "disable_app_for_user"
    assert decision.operation.risk == "high"
    assert "current user" in decision.message
    assert "2 targets" in decision.message


def test_main_frame_guard_blocks_declined_operation(monkeypatch):
    calls = []
    logs = []
    frame = SimpleNamespace(
        _dangerous_policy=DangerousOperationPolicy(),
        log_service=SimpleNamespace(log=lambda *args, **kwargs: logs.append((args, kwargs))),
    )
    monkeypatch.setattr(
        "gui.main_frame.AppSettings.instance",
        lambda: SimpleNamespace(get=lambda *_args: True),
    )
    monkeypatch.setattr(
        "gui.main_frame.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )

    def clear_app_data(devices, package):
        calls.append((devices, package))

    guarded = MainFrame._guard_dangerous_handler(frame, clear_app_data)
    guarded(["device-a"], "example.package")

    assert calls == []
    assert logs
    assert "example.package" not in str(logs)


def test_main_frame_guard_allows_when_confirmation_setting_is_disabled(monkeypatch):
    calls = []
    frame = SimpleNamespace(
        _dangerous_policy=DangerousOperationPolicy(),
        log_service=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "gui.main_frame.AppSettings.instance",
        lambda: SimpleNamespace(get=lambda *_args: False),
    )

    def uninstall_apk(devices, package):
        calls.append((devices, package))

    guarded = MainFrame._guard_dangerous_handler(frame, uninstall_apk)
    guarded(["device-a"], "example.package")

    assert calls == [(["device-a"], "example.package")]


def test_app_manager_dangerous_action_honors_decline(monkeypatch):
    logs = []
    dialog = SimpleNamespace(
        _dangerous_policy=DangerousOperationPolicy(),
        log=logs.append,
    )
    monkeypatch.setattr(
        "gui.dialogs.app_manager.AppSettings.instance",
        lambda: SimpleNamespace(get=lambda *_args: True),
    )
    monkeypatch.setattr(
        "gui.dialogs.app_manager.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )

    allowed = AppManagerDialog._confirm_dangerous_action(dialog, "uninstall", 2)

    assert allowed is False
    assert logs == ["Cancelled dangerous operation: uninstall"]
