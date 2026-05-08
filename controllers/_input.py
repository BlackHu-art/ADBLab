from __future__ import annotations

from controllers._base import _ADBControllerBase
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp


class ADBInputMixin(_ADBControllerBase):
    """Input events, shell commands, system settings."""

    # ── Provided by _ADBControllerBase ──
    advanced_model: ADBAdvanced
    app_model: ADBApp
    signals: ADBControllerSignals
    _pending_operations: dict

    _handlers = {
        "input_tap": "_process_input_tap_result",
        "input_swipe": "_process_input_swipe_result",
        "input_keyevent": "_process_input_keyevent_result",
        "input_text": "_process_input_text_result",
        "run_shell_command": "_process_run_shell_command_result",
        "settings_list": "_process_settings_list_result",
        "settings_get": "_process_settings_get_result",
        "settings_put": "_process_settings_put_result",
    }

    # ── 输入事件 ──

    def input_tap(self, devices: list, x: int, y: int):
        if not devices:
            self._emit_operation("input_tap", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.input_tap_async(ip, x, y)

    def _process_input_tap_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "input_tap", True, f"Tap ({result.get('x')},{result.get('y')}) on {ip}"
            )
        else:
            self._emit_operation("input_tap", False, f"Tap failed on {ip}: {result.get('error')}")

    def input_swipe(
        self, devices: list, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ):
        if not devices:
            self._emit_operation("input_swipe", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.input_swipe_async(ip, x1, y1, x2, y2, duration_ms)

    def _process_input_swipe_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("input_swipe", True, f"Swipe on {ip} completed")
        else:
            self._emit_operation(
                "input_swipe", False, f"Swipe failed on {ip}: {result.get('error')}"
            )

    def input_keyevent(self, devices: list, keycode: str):
        if not devices:
            self._emit_operation("input_keyevent", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.input_keyevent_async(ip, keycode)

    def _process_input_keyevent_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "input_keyevent", True, f"Key {result.get('keycode')} sent to {ip}"
            )
        else:
            self._emit_operation(
                "input_keyevent", False, f"Key event failed on {ip}: {result.get('error')}"
            )

    def input_text(self, devices: list, text: str):
        if not devices:
            self._emit_operation("input_text", False, "⚠️ No devices selected")
            return
        if not text.strip():
            self._emit_operation("input_text", False, "⚠️ Input text cannot be empty")
            return
        for device_ip in devices:
            self._send_text_to_device(device_ip, text)

    def _send_text_to_device(self, device_ip: str, text: str):
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("input_text", device_ip)
        self.app_model.input_text_async(device_ip, text)

    def _process_input_text_result(self, result: dict):
        device_ip = result.get("device_ip")
        text = result.get("text", "")
        if result.get("success"):
            self._emit_operation("input_text", True, f"Text '{text}' input on {device_ip}")
            self.signals.text_input.emit(device_ip, text)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            self._emit_operation(
                "input_text", False, f"Failed to input text on {device_ip}: {error_msg}"
            )

    # ── Shell ──

    def run_shell_command(self, devices: list, command: str):
        if not devices:
            self._emit_operation("shell_command", False, "⚠️ No devices selected")
            return
        if not command.strip():
            self._emit_operation("shell_command", False, "⚠️ Command cannot be empty")
            return
        for ip in devices:
            self.advanced_model.run_shell_command_async(ip, command)

    def _process_run_shell_command_result(self, result: dict):
        ip = result.get("device_ip", "")
        cmd = result.get("command", "")
        if result.get("success"):
            self._emit_operation(
                "shell_command", True, f"Shell [{ip}] `{cmd}`:\n{result.get('output', '')}"
            )
        else:
            self._emit_operation(
                "shell_command", False, f"Shell failed on {ip}: {result.get('error')}"
            )

    # ── 系统设置 ──

    def settings_list(self, devices: list, namespace: str = "system"):
        if not devices:
            self._emit_operation("settings_list", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.settings_list_async(ip, namespace)

    def _process_settings_list_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            ns = result.get("namespace", "")
            self._emit_operation(
                "settings_list", True, f"Settings [{ns}] ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "settings_list", False, f"Settings list failed on {ip}: {result.get('error')}"
            )

    def settings_get(self, devices: list, namespace: str, key: str):
        if not devices:
            self._emit_operation("settings_get", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.settings_get_async(ip, namespace, key)

    def _process_settings_get_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "settings_get",
                True,
                f"Setting [{result.get('key')}] = {result.get('value')} on {ip}",
            )
        else:
            self._emit_operation(
                "settings_get", False, f"Settings get failed on {ip}: {result.get('error')}"
            )

    def settings_put(self, devices: list, namespace: str, key: str, value: str):
        if not devices:
            self._emit_operation("settings_put", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.settings_put_async(ip, namespace, key, value)

    def _process_settings_put_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "settings_put", True, f"Set {result.get('key')}={result.get('value')} on {ip}"
            )
        else:
            self._emit_operation(
                "settings_put", False, f"Settings put failed on {ip}: {result.get('error')}"
            )
