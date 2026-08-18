"""集中定义需要用户明确确认的危险操作策略。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DangerousOperation:
    key: str
    label: str
    risk: str


@dataclass(frozen=True)
class PolicyDecision:
    operation: DangerousOperation | None
    requires_confirmation: bool
    message: str


_OPERATIONS = {
    "restart_devices": DangerousOperation("restart_devices", "Restart device", "high"),
    "restart_adb": DangerousOperation("restart_adb", "Restart the ADB server", "medium"),
    "reboot_mode": DangerousOperation("reboot_mode", "Reboot device into another mode", "high"),
    "tcpip_mode": DangerousOperation("tcpip_mode", "Change device ADB TCP/IP mode", "medium"),
    "cleanup_device_logs": DangerousOperation("cleanup_device_logs", "Delete device logs", "high"),
    "uninstall_apk": DangerousOperation("uninstall_apk", "Uninstall application", "high"),
    "clear_app_data": DangerousOperation("clear_app_data", "Clear application data", "high"),
    "disable_app": DangerousOperation("disable_app", "Disable application", "high"),
    "disable_app_for_user": DangerousOperation(
        "disable_app_for_user",
        "Disable application for the current user",
        "high",
    ),
    "force_stop": DangerousOperation("force_stop", "Force-stop application", "medium"),
    "kill_monkey": DangerousOperation("kill_monkey", "Stop Monkey processes", "medium"),
    "run_shell_command": DangerousOperation(
        "run_shell_command",
        "Execute an advanced shell command",
        "high",
    ),
    "remove_forwards": DangerousOperation("remove_forwards", "Remove port forwards", "medium"),
    "remove_reverse": DangerousOperation(
        "remove_reverse",
        "Remove reverse port forwards",
        "medium",
    ),
    "settings_put": DangerousOperation("settings_put", "Modify an Android setting", "high"),
    "kill_process": DangerousOperation("kill_process", "Terminate a device process", "high"),
    "battery_set": DangerousOperation("battery_set", "Override device battery state", "medium"),
    "battery_reset": DangerousOperation(
        "battery_reset",
        "Reset overridden battery state",
        "medium",
    ),
    "quick_setting": DangerousOperation("quick_setting", "Modify device quick settings", "medium"),
    "ime_set": DangerousOperation("ime_set", "Change the active input method", "medium"),
    "uninstall": DangerousOperation("uninstall", "Uninstall application", "high"),
    "clear": DangerousOperation("clear", "Clear application data", "high"),
    "disable": DangerousOperation("disable", "Disable application", "high"),
}


class DangerousOperationPolicy:
    """判断已知危险操作是否需要用户确认。"""

    def evaluate(
        self,
        operation_key: str,
        *,
        confirmation_enabled: bool,
        target_count: int = 1,
    ) -> PolicyDecision:
        """根据全局开关和目标数量生成危险操作确认决策。"""
        operation = _OPERATIONS.get(operation_key)
        if operation is None:
            return PolicyDecision(None, False, "")
        count = max(1, int(target_count))
        target_text = "1 target" if count == 1 else f"{count} targets"
        message = (
            f"{operation.label} on {target_text}?\n\n"
            "This operation can interrupt services or remove device data."
        )
        return PolicyDecision(operation, bool(confirmation_enabled), message)
