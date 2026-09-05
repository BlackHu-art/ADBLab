"""提供设备连接、发现和基础信息查询。

本模块只依赖核心 adb_model，避免模型之间形成循环依赖。
"""

import re
import time

from core.exec import CommandRunner

from .adb_model import ADBModelCore, async_command

BASIC_PROP_FIELDS = {
    "Model": "ro.product.model",
    "Brand": "ro.product.brand",
    "Aversion": "ro.build.version.release",
    "SDK Version": "ro.build.version.sdk",
    "CPU Architecture": "ro.product.cpu.abi",
    "Hardware": "ro.hardware",
}

FULL_PROP_FIELDS = {
    "Model": "ro.product.model",
    "Brand": "ro.product.brand",
    "Android Version": "ro.build.version.release",
    "Serial Number": "ro.serialno",
    "SDK Version": "ro.build.version.sdk",
    "CPU Architecture": "ro.product.cpu.abi",
    "Hardware": "ro.hardware",
    "Timezone": "persist.sys.timezone",
}

GETPROP_LINE_RE = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")
INFO_MARKERS = {
    "PROPS": "__ADBLAB_PROPS__",
    "DF": "__ADBLAB_DF__",
    "MEMINFO": "__ADBLAB_MEMINFO__",
    "WM": "__ADBLAB_WM__",
    "IP": "__ADBLAB_IP__",
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


def parse_getprop_output(output: str) -> dict[str, str]:
    """将 adb shell getprop 输出解析为属性字典。"""
    props: dict[str, str] = {}
    for raw_line in output.splitlines():
        match = GETPROP_LINE_RE.match(raw_line.strip())
        if match:
            props[match.group(1)] = match.group(2)
    return props


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


def _meminfo_value(output: str, key: str) -> str:
    prefix = f"{key}:"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped
    return "N/A"


def _line_with_prefix(output: str, prefix: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped
    return "N/A"


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
        r = self._run(["adb", "devices"])
        if not r["success"]:
            return {"success": False, "error": r["error"], "devices": []}
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
        r = self._run(["adb", "-s", device, "get-state"])
        if not r["success"] or "device" not in r.get("output", ""):
            return {
                "device_ip": device,
                "success": False,
                "error": f"Abnormal device status: {r.get('output', r.get('error', ''))}",
                "requires_refresh": False,
            }
        r = self._run(["adb", "-s", device, "reboot"], timeout=3)
        if r["success"] or (not r["success"] and "Timeout" in r.get("error", "")):
            return {
                "device_ip": device,
                "success": True,
                "requires_refresh": True,
                "raw_result": "The device is starting to restart",
            }
        return {
            "device_ip": device,
            "success": False,
            "error": r.get("error", r.get("output", "abnormal return")),
            "requires_refresh": False,
        }

    @async_command
    def restart_adb_async(self) -> dict:
        kill = self._run(["adb", "kill-server"])
        if not kill["success"]:
            return {"success": False, "error": f"kill-server: {kill['error']}"}
        time.sleep(1)
        r = self._run(["adb", "start-server"], timeout=5)
        return {"success": r["success"], "error": r["error"] if not r["success"] else ""}

    @async_command(long_running=True)
    def get_device_info_async(self, device: str) -> dict[str, str]:
        info = self._fetch_full_device_info(device)
        info["device_ip"] = device
        info["ip"] = device
        return info

    @staticmethod
    def get_devices_basic_info(device):
        """供 DeviceStore 快速查询使用的同步封装。"""
        return ADBDevice._fetch_properties(device, BASIC_PROP_FIELDS)

    @staticmethod
    def get_device_overview_info(device: str) -> dict[str, str]:
        """在既有后台发现任务中一次读取概览属性；失败回退基础信息，不增加 GUI 查询。"""

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
        result = CommandRunner.run(["adb", "-s", device, "shell", command], timeout=15)
        if result.success and OVERVIEW_MARKERS["BASIC"] in result.output:
            return parse_device_overview(result.output)
        return ADBDevice.get_devices_basic_info(device)

    @staticmethod
    def _fetch_properties(device: str, field_map: dict[str, str]) -> dict[str, str]:
        if field_map == BASIC_PROP_FIELDS:
            return ADBDevice._fetch_basic_properties(device)
        result = CommandRunner.run(
            ["adb", "-s", device, "shell", "getprop"],
            timeout=15,
        )
        if result.success:
            props = parse_getprop_output(result.output)
            return {label: props.get(prop, "") for label, prop in field_map.items()}
        commands = {
            label: ["adb", "-s", device, "shell", "getprop", prop]
            for label, prop in field_map.items()
        }
        return ADBModelCore._fetch_device_info(commands)

    @staticmethod
    def _fetch_basic_properties(device: str) -> dict[str, str]:
        labels = list(BASIC_PROP_FIELDS.keys())
        props = list(BASIC_PROP_FIELDS.values())
        result = CommandRunner.run(
            ["adb", "-s", device, "shell", "; ".join(f"getprop {prop}" for prop in props)],
            timeout=15,
        )
        if result.success:
            values = result.output.splitlines()
            return {
                label: values[index].strip() if index < len(values) else ""
                for index, label in enumerate(labels)
            }
        commands = {
            label: ["adb", "-s", device, "shell", "getprop", prop]
            for label, prop in BASIC_PROP_FIELDS.items()
        }
        return ADBModelCore._fetch_device_info(commands)

    @staticmethod
    def _fetch_full_device_info(device: str) -> dict[str, str]:
        command = " ; ".join(
            [
                f"echo {INFO_MARKERS['PROPS']}",
                "getprop",
                f"echo {INFO_MARKERS['DF']}",
                "df -h /data",
                f"echo {INFO_MARKERS['MEMINFO']}",
                "cat /proc/meminfo",
                f"echo {INFO_MARKERS['WM']}",
                "wm size; wm density",
                f"echo {INFO_MARKERS['IP']}",
                "ip addr show wlan0",
            ]
        )
        result = CommandRunner.run(
            ["adb", "-s", device, "shell", command],
            timeout=15,
        )
        if not result.success:
            info = ADBDevice._fetch_properties(device, FULL_PROP_FIELDS)
            info.update(ADBDevice._fetch_device_probe_info(device))
            return info
        sections = parse_labeled_sections(result.output, INFO_MARKERS)
        props = parse_getprop_output(sections["PROPS"])
        info = {label: props.get(prop, "") for label, prop in FULL_PROP_FIELDS.items()}
        wm_output = sections["WM"]
        info.update(
            {
                "Storage": sections["DF"] or "N/A",
                "Total Memory": _meminfo_value(sections["MEMINFO"], "MemTotal"),
                "Available Memory": _meminfo_value(sections["MEMINFO"], "MemAvailable"),
                "Resolution": _line_with_prefix(wm_output, "Physical size:"),
                "Density": _line_with_prefix(wm_output, "Physical density:"),
                "Mac": sections["IP"] or "N/A",
            }
        )
        return info

    @staticmethod
    def _fetch_device_probe_info(device: str) -> dict[str, str]:
        probes = {
            "Storage": ["adb", "-s", device, "shell", "df", "-h", "/data"],
            "Meminfo": ["adb", "-s", device, "shell", "cat", "/proc/meminfo"],
            "Wm": ["adb", "-s", device, "shell", "wm size; wm density"],
            "Mac": ["adb", "-s", device, "shell", "ip", "addr", "show", "wlan0"],
        }
        raw = {
            key: result.output if result.success else "N/A"
            for key, result in (
                (key, CommandRunner.run(command, timeout=15)) for key, command in probes.items()
            )
        }
        wm_output = raw["Wm"]
        return {
            "Storage": raw["Storage"],
            "Total Memory": _meminfo_value(raw["Meminfo"], "MemTotal"),
            "Available Memory": _meminfo_value(raw["Meminfo"], "MemAvailable"),
            "Resolution": _line_with_prefix(wm_output, "Physical size:"),
            "Density": _line_with_prefix(wm_output, "Physical density:"),
            "Mac": raw["Mac"],
        }
