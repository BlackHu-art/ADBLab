"""协调设备诊断、日志导出和电池、进程控制的准入与反馈。"""

from __future__ import annotations

import os
from datetime import datetime

from controllers._base import _ADBControllerBase
from models.adb_advanced import ADBAdvanced
from utils.adb_values import normalize_android_package, truncate_diagnostic_output
from utils.diagnostic_artifacts import diagnostic_log_filename


def _emit_readonly_diagnostic_result(
    controller,
    result: dict,
    *,
    operation: str,
    label: str,
    max_lines: int,
) -> None:
    """把固定命令的结果裁剪后发布到可见操作日志。"""

    ip = result.get("device_ip", "")
    if not result.get("success"):
        controller._emit_operation(
            operation,
            False,
            f"{label} failed on {ip}: {result.get('error')}",
        )
        return
    output, truncated = truncate_diagnostic_output(
        result.get("output", ""),
        max_lines=max_lines,
    )
    suffix = " [truncated]" if truncated else ""
    controller._emit_operation(
        operation,
        True,
        f"{label} ({ip}){suffix}:\n{output}",
    )


class ADBDiagnosticsMixin(_ADBControllerBase):
    """协调设备诊断与控制的参数准入、模型提交及结果呈现。"""

    # 以下属性由 _ADBControllerBase 提供。
    advanced_model: ADBAdvanced

    _handlers = {
        "dumpsys_meminfo": "_process_dumpsys_meminfo_result",
        "dumpsys_cpuinfo": "_process_dumpsys_cpuinfo_result",
        "dumpsys_battery": "_process_dumpsys_battery_result",
        "top_snapshot": "_process_top_snapshot_result",
        "gfxinfo": "_process_gfxinfo_result",
        "wakelocks": "_process_wakelocks_result",
        "netstats_detail": "_process_netstats_detail_result",
        "battery_set_level": "_process_battery_set_level_result",
        "battery_set_status": "_process_battery_set_status_result",
        "battery_reset": "_process_battery_reset_result",
        "logcat_filtered": "_process_logcat_filtered_result",
        "list_processes": "_process_list_processes_result",
        "kill_process": "_process_kill_process_result",
        "get_device_uptime": "_process_get_device_uptime_result",
    }

    def dumpsys_meminfo(self, devices: list, package: str = ""):
        if not self._require_devices(devices, "dumpsys_meminfo"):
            return
        for ip in devices:
            self.advanced_model.dumpsys_meminfo_async(ip, package)

    def _process_dumpsys_meminfo_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "dumpsys_meminfo",
                True,
                f"📊 Memory info ({ip}):\n{result.get('output', '')[:2000]}",
            )
        else:
            self._emit_operation(
                "dumpsys_meminfo", False, f"Meminfo failed on {ip}: {result.get('error')}"
            )

    def dumpsys_cpuinfo(self, devices: list):
        if not self._require_devices(devices, "dumpsys_cpuinfo"):
            return
        for ip in devices:
            self.advanced_model.dumpsys_cpuinfo_async(ip)

    def _process_dumpsys_cpuinfo_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "dumpsys_cpuinfo", True, f"📊 CPU info ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "dumpsys_cpuinfo", False, f"CPU info failed on {ip}: {result.get('error')}"
            )

    def dumpsys_battery(self, devices: list):
        if not self._require_devices(devices, "dumpsys_battery"):
            return
        for ip in devices:
            self.advanced_model.dumpsys_battery_async(ip)

    def _process_dumpsys_battery_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "dumpsys_battery",
                True,
                f"🔋 Battery info ({ip}):\n{result.get('output', '')[:1000]}",
            )
        else:
            self._emit_operation(
                "dumpsys_battery", False, f"Battery info failed on {ip}: {result.get('error')}"
            )

    def top_snapshot(self, devices: list):
        if not self._require_devices(devices, "top_snapshot"):
            return
        for ip in devices:
            self.advanced_model.top_snapshot_async(ip)

    def _process_top_snapshot_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="top_snapshot",
            label="Top snapshot",
            max_lines=20,
        )

    def gfxinfo(self, devices: list, package: str):
        if not self._require_devices(devices, "gfxinfo"):
            return
        try:
            package = normalize_android_package(package)
        except ValueError as exc:
            self._emit_operation("gfxinfo", False, str(exc))
            return
        for ip in devices:
            self.advanced_model.gfxinfo_async(ip, package)

    def _process_gfxinfo_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="gfxinfo",
            label="GFX info",
            max_lines=60,
        )

    def wakelocks(self, devices: list):
        if not self._require_devices(devices, "wakelocks"):
            return
        for ip in devices:
            self.advanced_model.wakelocks_async(ip)

    def _process_wakelocks_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="wakelocks",
            label="Wakelocks",
            max_lines=40,
        )

    def netstats_detail(self, devices: list):
        if not self._require_devices(devices, "netstats_detail"):
            return
        for ip in devices:
            self.advanced_model.netstats_detail_async(ip)

    def _process_netstats_detail_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="netstats_detail",
            label="Network statistics",
            max_lines=60,
        )

    # 电池状态

    def battery_set(self, devices: list, param: str, value: str):
        if not self._require_devices(devices, "battery_set"):
            return
        try:
            numeric_value = int(str(value).strip())
        except (TypeError, ValueError):
            self._emit_operation("battery_set", False, "Battery value must be an integer")
            return
        if param == "level" and not 0 <= numeric_value <= 100:
            self._emit_operation("battery_set", False, "Battery level must be between 0 and 100")
            return
        if param == "status" and not 1 <= numeric_value <= 5:
            self._emit_operation("battery_set", False, "Battery status must be between 1 and 5")
            return
        if param not in {"level", "status"}:
            self._emit_operation("battery_set", False, "Unsupported battery parameter")
            return
        for ip in devices:
            if param == "level":
                self.advanced_model.battery_set_level_async(ip, numeric_value)
            elif param == "status":
                self.advanced_model.battery_set_status_async(ip, str(numeric_value))

    def _process_battery_set_level_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "battery_set", True, f"Battery level set to {result.get('level')}% on {ip}"
            )
        else:
            self._emit_operation(
                "battery_set", False, f"Battery set failed on {ip}: {result.get('error')}"
            )

    def _process_battery_set_status_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "battery_set", True, f"Battery status set to '{result.get('status')}' on {ip}"
            )
        else:
            self._emit_operation(
                "battery_set", False, f"Battery set failed on {ip}: {result.get('error')}"
            )

    def battery_reset(self, devices: list):
        if not self._require_devices(devices, "battery_reset"):
            return
        for ip in devices:
            self.advanced_model.battery_reset_async(ip)

    def _process_battery_reset_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("battery_reset", True, f"Battery reset on {ip}")
        else:
            self._emit_operation(
                "battery_reset", False, f"Battery reset failed on {ip}: {result.get('error')}"
            )

    # Logcat 日志

    def logcat_filtered(
        self,
        devices: list,
        buffer: str = "main",
        priority: str = "V",
        tag_filter: str = "",
        regex: str = "",
    ):
        if not self._require_devices(devices, "logcat_filtered"):
            return
        try:
            save_dir = self._get_screenshot_dir()
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_operation(
                "logcat_filtered", False, f"Failed to prepare logcat directory: {exc}"
            )
            return
        for ip in devices:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(save_dir, diagnostic_log_filename("logcat", ip, timestamp))
            self.advanced_model.logcat_filtered_async(
                ip, log_path, buffer, priority, tag_filter, regex
            )

    def _process_logcat_filtered_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "logcat_filtered",
                True,
                f"Filtered log saved for {ip} ({result.get('line_count', 0)} lines)",
            )
        else:
            self._emit_operation(
                "logcat_filtered", False, f"Logcat filter failed on {ip}: {result.get('error')}"
            )

    # 设备进程

    def list_processes(self, devices: list):
        if not self._require_devices(devices, "list_processes"):
            return
        for ip in devices:
            self.advanced_model.list_processes_async(ip)

    def _process_list_processes_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "list_processes", True, f"Processes ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "list_processes", False, f"Process list failed on {ip}: {result.get('error')}"
            )

    def kill_process(self, devices: list, pid: str):
        if not self._require_devices(devices, "kill_process"):
            return
        devices = list(dict.fromkeys(devices))
        if len(devices) != 1:
            self._emit_operation("kill_process", False, "PID 仅属于单台设备，请只选择一台设备")
            return
        text = str(pid).strip()
        # isdigit 接受上标等 Unicode 数字，但 int() 会抛 ValueError；先限 ASCII 再转换。
        if not text.isascii() or not text.isdigit():
            self._emit_operation("kill_process", False, "PID must be a positive integer")
            return
        pid_value = int(text)
        if not 1 <= pid_value <= 2_147_483_647:
            self._emit_operation("kill_process", False, "PID must be a positive integer")
            return
        for ip in devices:
            self.advanced_model.kill_process_async(ip, str(pid_value))

    def _process_kill_process_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("kill_process", True, f"Killed PID {result.get('pid')} on {ip}")
        else:
            self._emit_operation(
                "kill_process", False, f"Kill failed on {ip}: {result.get('error')}"
            )

    # 设备运行时长

    def device_uptime(self, devices: list):
        if not self._require_devices(devices, "device_uptime"):
            return
        for ip in devices:
            self.advanced_model.get_device_uptime_async(ip)

    def _process_get_device_uptime_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "device_uptime", True, f"Uptime ({ip}): {result.get('output', '')}"
            )
        else:
            self._emit_operation(
                "device_uptime", False, f"Uptime failed on {ip}: {result.get('error')}"
            )
