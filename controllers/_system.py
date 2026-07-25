"""提供权限、应用控制、广播、Activity、输入法和模拟器控制能力。"""

from __future__ import annotations

from controllers._base import _ADBControllerBase
from core.log_service import LogService
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced


class ADBSystemControllerMixin(_ADBControllerBase):
    """协调权限、应用状态、广播、Activity、输入法和模拟器操作。"""

    advanced_model: ADBAdvanced
    signals: ADBControllerSignals
    log_service: LogService

    _handlers = {
        "grant_permission": "_process_grant_permission_result",
        "revoke_permission": "_process_revoke_permission_result",
        "disable_package": "_process_disable_package_result",
        "enable_package": "_process_enable_package_result",
        "force_stop": "_process_force_stop_result",
        "send_broadcast": "_process_send_broadcast_result",
        "start_activity": "_process_start_activity_result",
        "open_deep_link": "_process_open_deep_link_result",
        "ime_list": "_process_ime_list_result",
        "ime_set": "_process_ime_set_result",
        "emu_sms_send": "_process_emu_sms_send_result",
        "emu_call": "_process_emu_call_result",
        "emu_geo_fix": "_process_emu_geo_fix_result",
    }

    # 权限管理

    def grant_permission(self, devices: list, package: str, permission: str):
        if not self._require_devices(devices, "grant_permission"):
            return
        for ip in devices:
            self.advanced_model.grant_permission_async(ip, package, permission)

    def _process_grant_permission_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "grant_permission", True,
                f"Granted {result.get('permission')} to {result.get('package')} on {ip}",
            )
        else:
            self._emit_operation(
                "grant_permission", False, f"Grant failed on {ip}: {result.get('error')}"
            )

    def revoke_permission(self, devices: list, package: str, permission: str):
        if not self._require_devices(devices, "revoke_permission"):
            return
        for ip in devices:
            self.advanced_model.revoke_permission_async(ip, package, permission)

    def _process_revoke_permission_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "revoke_permission", True,
                f"Revoked {result.get('permission')} from {result.get('package')} on {ip}",
            )
        else:
            self._emit_operation(
                "revoke_permission", False, f"Revoke failed on {ip}: {result.get('error')}"
            )

    # 应用启用、停用和强制停止

    def disable_app(self, devices: list, package: str):
        if not self._require_devices(devices, "disable_app"):
            return
        for ip in devices:
            self.advanced_model.disable_package_async(ip, package)

    def _process_disable_package_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("disable_app", True, f"Disabled {result.get('package')} on {ip}")
        else:
            self._emit_operation(
                "disable_app", False, f"Disable failed on {ip}: {result.get('error')}"
            )

    def enable_app(self, devices: list, package: str):
        if not self._require_devices(devices, "enable_app"):
            return
        for ip in devices:
            self.advanced_model.enable_package_async(ip, package)

    def _process_enable_package_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("enable_app", True, f"Enabled {result.get('package')} on {ip}")
        else:
            self._emit_operation(
                "enable_app", False, f"Enable failed on {ip}: {result.get('error')}"
            )

    def force_stop(self, devices: list, package: str):
        if not self._require_devices(devices, "force_stop"):
            return
        for ip in devices:
            self.advanced_model.force_stop_async(ip, package)

    def _process_force_stop_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("force_stop", True, f"Force stopped app on {ip}")
        else:
            self._emit_operation(
                "force_stop", False, f"Force stop failed on {ip}: {result.get('error')}"
            )

    # 广播、Activity 和 Deep Link

    def send_broadcast(self, devices: list, action: str):
        if not self._require_devices(devices, "send_broadcast"):
            return
        for ip in devices:
            self.advanced_model.send_broadcast_async(ip, action)

    def _process_send_broadcast_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "send_broadcast", True, f"Broadcast sent on {ip}:\n{result.get('output', '')}"
            )
        else:
            self._emit_operation(
                "send_broadcast", False, f"Broadcast failed on {ip}: {result.get('error')}"
            )

    def start_activity(self, devices: list, component_or_action: str):
        if not self._require_devices(devices, "start_activity"):
            return
        spec = component_or_action.strip()
        for ip in devices:
            if "/" in spec:
                self.advanced_model.start_activity_async(ip, component=spec)
            elif spec.startswith("http"):
                self.advanced_model.open_deep_link_async(ip, spec)
            else:
                self.advanced_model.start_activity_async(ip, action=spec)

    def _process_start_activity_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "start_activity", True, f"Activity started on {ip}:\n{result.get('output', '')}"
            )
        else:
            self._emit_operation(
                "start_activity", False, f"Start activity failed on {ip}: {result.get('error')}"
            )

    def open_deep_link(self, devices: list, uri: str):
        if not self._require_devices(devices, "deep_link"):
            return
        for ip in devices:
            self.advanced_model.open_deep_link_async(ip, uri)

    def _process_open_deep_link_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "deep_link", True, f"Deep link opened on {ip}: {result.get('uri')}"
            )
        else:
            self._emit_operation(
                "deep_link", False, f"Deep link failed on {ip}: {result.get('error')}"
            )

    # 输入法

    def ime_list(self, devices: list):
        if not self._require_devices(devices, "ime_list"):
            return
        for ip in devices:
            self.advanced_model.ime_list_async(ip)

    def _process_ime_list_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("ime_list", True, f"IME list ({ip}):\n{result.get('output', '')}")
        else:
            self._emit_operation(
                "ime_list", False, f"IME list failed on {ip}: {result.get('error')}"
            )

    def ime_set(self, devices: list, ime_id: str):
        if not self._require_devices(devices, "ime_set"):
            return
        for ip in devices:
            self.advanced_model.ime_set_async(ip, ime_id)

    def _process_ime_set_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("ime_set", True, f"IME set on {ip}")
        else:
            self._emit_operation("ime_set", False, f"IME set failed on {ip}: {result.get('error')}")

    # 模拟器

    def emu_sms(self, devices: list, sender: str, text: str):
        if not self._require_devices(devices, "emu_sms"):
            return
        for ip in devices:
            self.advanced_model.emu_sms_send_async(ip, sender, text)

    def _process_emu_sms_send_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("emu_sms", True, f"SMS from {result.get('sender')} sent to {ip}")
        else:
            self._emit_operation("emu_sms", False, f"Emu SMS failed on {ip}: {result.get('error')}")

    def emu_call(self, devices: list, number: str):
        if not self._require_devices(devices, "emu_call"):
            return
        for ip in devices:
            self.advanced_model.emu_call_async(ip, number)

    def _process_emu_call_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("emu_call", True, f"Call to {result.get('number')} on {ip}")
        else:
            self._emit_operation(
                "emu_call", False, f"Emu call failed on {ip}: {result.get('error')}"
            )

    def emu_geo(self, devices: list, longitude: str, latitude: str):
        if not self._require_devices(devices, "emu_geo"):
            return
        for ip in devices:
            self.advanced_model.emu_geo_fix_async(ip, longitude, latitude)

    def _process_emu_geo_fix_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "emu_geo", True,
                f"GPS set on {ip}: {result.get('longitude')},{result.get('latitude')}",
            )
        else:
            self._emit_operation("emu_geo", False, f"Emu geo failed on {ip}: {result.get('error')}")
