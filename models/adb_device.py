"""提供设备连接、发现和基础信息查询。

本模块只依赖核心 adb_model，避免模型之间形成循环依赖。
"""

import re
import time
from collections.abc import Callable

from core.exec import CommandResult, CommandRunner

from .adb_model import ADBModelCore, async_command

BASIC_PROP_FIELDS = {
    "Model": "ro.product.model",
    "Brand": "ro.product.brand",
    "Aversion": "ro.build.version.release",
    "SDK Version": "ro.build.version.sdk",
    "CPU Architecture": "ro.product.cpu.abi",
    "Hardware": "ro.hardware",
}

OVERVIEW_MARKERS = {
    key: f"__ADBLAB_OVERVIEW_{key}__" for key in ("BASIC", "MEMORY", "STORAGE", "SCREEN", "BATTERY")
}


def parse_device_overview(output: str) -> dict[str, str]:
    """解析概览只读快照；仅接受有明确单位和有效范围的属性，不保存原始诊断输出。"""

    sections = parse_labeled_sections(output, OVERVIEW_MARKERS, preserve_empty_lines=True)
    values = sections["BASIC"].splitlines()
    info = {
        label: values[index].strip() if index < len(values) else ""
        for index, label in enumerate(BASIC_PROP_FIELDS)
    }
    for source, target in (("MemTotal", "Total Memory"), ("MemAvailable", "Available Memory")):
        match = re.search(rf"(?m)^{source}:\s*(\d+)\s+kB\s*$", sections["MEMORY"])
        if match:
            info[target] = f"{int(match[1]) / (1024 * 1024):.1f} GiB"
    for line in sections["STORAGE"].splitlines():
        match = re.match(r"^\S+\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s+\S+", line.strip())
        if match:
            total, used, available = map(int, match.groups())
            if total > 0 and used <= total and available <= total:
                info["Storage Total"] = f"{total / (1024 * 1024):.1f} GiB"
                info["Storage Available"] = f"{available / (1024 * 1024):.1f} GiB"
    dimensions = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", sections["SCREEN"])
    if dimensions and all(int(value) > 0 for value in dimensions[-1]):
        info["Resolution"] = " × ".join(dimensions[-1])
    density = re.findall(r"(?:Physical|Override) density:\s*(\d+)", sections["SCREEN"])
    if density and int(density[-1]) > 0:
        info["Density"] = f"{density[-1]} dpi"
    battery = dict(re.findall(r"(?m)^\s*(level|scale|status):\s*(\d+)\s*$", sections["BATTERY"]))
    level, scale = int(battery.get("level", "-1")), int(battery.get("scale", "0"))
    if scale > 0 and 0 <= level <= scale:
        info["Battery Level"] = f"{round(level * 100 / scale)}%"
    statuses = {"2": "充电中", "3": "使用电池", "4": "未充电", "5": "已充满"}
    status = statuses.get(battery.get("status", ""))
    if status:
        info["Battery Status"] = status
    return info


def parse_connected_devices(output: str) -> list[str]:
    devices = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def parse_labeled_sections(
    output: str, markers: dict[str, str], *, preserve_empty_lines: bool = False,
) -> dict[str, str]:
    """按显式分段标记拆分批量 Shell 输出。"""
    sections = {key: "" for key in markers}
    marker_to_key = {marker: key for key, marker in markers.items()}
    current_key = ""
    lines: dict[str, list[str]] = {key: [] for key in markers}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line in marker_to_key:
            current_key = marker_to_key[line]
            continue
        if current_key:
            lines[current_key].append(raw_line)
    for key, section_lines in lines.items():
        text = "\n".join(section_lines)
        sections[key] = text if preserve_empty_lines else text.strip()
    return sections


def _read_info_command(
    command: list[str], deadline: float, cancelled: Callable[[], bool] | None,
    *, max_timeout: float | None = None,
) -> CommandResult | None:
    """在同一查询预算内执行只读命令；取消后连成功结果也不交给属性解析。"""
    remaining = deadline - time.monotonic()
    if remaining <= 0 or (cancelled is not None and cancelled()):
        return None
    timeout = remaining if max_timeout is None else min(remaining, max_timeout)
    result = CommandRunner.run(command, timeout=timeout, cancelled=cancelled)
    return None if cancelled is not None and cancelled() else result


class ADBDevice(ADBModelCore):
    """封装设备连接、断开、重启和信息查询。"""

    @async_command
    def connect_device_async(self, ip_address: str) -> dict:
        r = self._run(["adb", "connect", ip_address])
        return {
            "success": r.get("success", False),
            "device_ip": ip_address,
            "output": r.get("output", ""),
            "error": r.get("error", ""),
        }

    @async_command
    def get_connected_devices_async(self) -> dict:
        """读取在线设备；已被更新结果取代的查询按取消收尾，不发布旧列表或报告连接失败。"""
        r = self._run_readonly(["adb", "devices"])
        if r.get("stale"):
            return {
                **r, "cancelled": True, "devices": [],
                "message": "设备列表已更新，本次刷新结果已忽略",
            }
        if not r["success"]:
            return {**r, "devices": []}
        return {"success": True, "devices": parse_connected_devices(r["output"])}

    @async_command
    def disconnect_device_async(self, device: str) -> dict:
        r = self._run(["adb", "disconnect", device], device=device)
        return {
            "device_ip": device,
            "raw_result": r.get("output", r.get("error", "")),
            "success": "disconnected" in r.get("output", "").lower(),
        }

    @async_command
    def restart_device_async(self, device: str) -> dict:
        """提交设备重启；命令成功不代表设备已上线，超时无法确认是否已提交。"""
        r = self._run(["adb", "-s", device, "get-state"])
        if not r["success"] or "device" not in r.get("output", ""):
            return {
                "device_ip": device,
                "success": False,
                "error": f"Abnormal device status: {r.get('output', r.get('error', ''))}",
                "requires_refresh": False,
            }
        # 原生客户端启动可能已超过数秒，沿用统一命令预算，不能把启动超时视为重启成功。
        r = self._run(["adb", "-s", device, "reboot"])
        if r["success"]:
            return {
                "device_ip": device,
                "success": True,
                "requires_refresh": True,
                "raw_result": "Reboot request submitted; device startup has not been verified",
            }
        if "timeout" in r.get("error", "").lower():
            return {
                "device_ip": device,
                "success": False,
                "error": "Reboot result unknown after timeout; check device status before retrying",
                "requires_refresh": True,
            }
        return {
            "device_ip": device,
            "success": False,
            "error": r.get("error", r.get("output", "abnormal return")),
            "requires_refresh": False,
        }

    @async_command
    def restart_adb_async(self) -> dict:
        """重启本机 ADB 服务；启动阶段使用包含原生客户端开销的统一命令预算。"""
        kill = self._run(["adb", "kill-server"])
        if not kill["success"]:
            return {"success": False, "error": f"kill-server: {kill['error']}"}
        time.sleep(1)
        r = self._run(["adb", "start-server"])
        return {"success": r["success"], "error": r["error"] if not r["success"] else ""}

    @staticmethod
    def get_devices_basic_info(
        device: str, *, timeout: float = 15, cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, str]:
        """在调用方预算内查询基础属性；兼容回退与首个命令共享截止时间。"""
        return ADBDevice._fetch_basic_properties(
            device, deadline=time.monotonic() + max(0, timeout), cancelled=cancelled,
        )

    @staticmethod
    def get_device_overview_info(
        device: str, *, timeout: float = 15, cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, str]:
        """一次读取概览；仅响应格式不兼容时补查基础信息，所有查询共享预算与取消。"""

        deadline = time.monotonic() + max(0, timeout)
        commands = {
            "BASIC": "; ".join(f"getprop {prop}" for prop in BASIC_PROP_FIELDS.values()),
            "MEMORY": "cat /proc/meminfo",
            "STORAGE": "df -k /data",
            "SCREEN": "wm size; wm density",
            "BATTERY": "dumpsys battery",
        }
        command = "; ".join(
            f"echo {OVERVIEW_MARKERS[key]}; {probe}" for key, probe in commands.items()
        )
        result = _read_info_command(["adb", "-s", device, "shell", command], deadline, cancelled)
        if result is None or not result.success:
            return {}
        if OVERVIEW_MARKERS["BASIC"] in result.output:
            return parse_device_overview(result.output)
        return ADBDevice._fetch_basic_properties(device, deadline=deadline, cancelled=cancelled)

    @staticmethod
    def _fetch_basic_properties(
        device: str, *, deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, str]:
        """合并基础属性读取；明确的脚本语法不兼容才逐项重查，连接失败不重复请求。"""
        if deadline is None:
            deadline = time.monotonic() + 15
        labels = list(BASIC_PROP_FIELDS.keys())
        props = list(BASIC_PROP_FIELDS.values())
        result = _read_info_command(
            ["adb", "-s", device, "shell", "; ".join(f"getprop {prop}" for prop in props)],
            deadline, cancelled,
        )
        if result is None:
            return {}
        if result.success:
            values = result.output.splitlines()
            return {
                label: values[index].strip() if index < len(values) else ""
                for index, label in enumerate(labels)
            }
        if result.returncode <= 0 or "syntax error" not in result.error.lower():
            return {}
        info = {}
        for label, prop in BASIC_PROP_FIELDS.items():
            item = _read_info_command(
                ["adb", "-s", device, "shell", "getprop", prop], deadline, cancelled,
                max_timeout=5,
            )
            if item is None or not item.success:
                break
            info[label] = item.output
        return {} if cancelled is not None and cancelled() else info
