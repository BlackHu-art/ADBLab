"""
Device connection, discovery, and info retrieval.

Imports only from adb_model (core) — no circular dependencies.
"""

import time

from .adb_model import ADBModelCore, async_command


def parse_connected_devices(output: str) -> list[str]:
    devices = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


class ADBDevice(ADBModelCore):
    """Device management: connect, disconnect, restart, and info queries."""

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
    def get_connected_devices_async(self):
        r = self._run(["adb", "devices"])
        if not r["success"]:
            return []
        return parse_connected_devices(r["output"])

    @async_command
    def disconnect_device_async(self, device: str) -> dict:
        r = self._run(["adb", "disconnect", device], device=device)
        return {
            "device_ip": device, "raw_result": r.get("output", r.get("error", "")),
            "success": "disconnected" in r.get("output", "").lower(),
        }

    @async_command
    def restart_device_async(self, device: str) -> dict:
        r = self._run(["adb", "-s", device, "get-state"])
        if not r["success"] or "device" not in r.get("output", ""):
            return {"device_ip": device, "success": False,
                    "error": f"Abnormal device status: {r.get('output', r.get('error', ''))}",
                    "requires_refresh": False}
        # reboot 超时 = 设备正在重启 = 成功（_run 内部捕获 TimeoutExpired 返回 success=False）
        r = self._run(["adb", "-s", device, "reboot"], timeout=3)
        if not r["success"] and "Timeout" in r.get("error", ""):
            return {"device_ip": device, "success": True,
                    "requires_refresh": True,
                    "raw_result": "The device is starting to restart"}
        return {"device_ip": device, "success": False,
                "error": r.get("error", r.get("output", "abnormal return")),
                "requires_refresh": False}

    @async_command
    def restart_adb_async(self) -> dict:
        self._run(["adb", "kill-server"])
        time.sleep(1)
        r = self._run(["adb", "start-server"], timeout=5)
        return {"success": r["success"], "error": r["error"] if not r["success"] else ""}

    @async_command
    def get_device_info_async(self, device: str) -> dict[str, str]:
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Android Version": [
                "adb",
                "-s",
                device,
                "shell",
                "getprop",
                "ro.build.version.release",
            ],
            "Serial Number": ["adb", "-s", device, "shell", "getprop", "ro.serialno"],
            "SDK Version": ["adb", "-s", device, "shell", "getprop", "ro.build.version.sdk"],
            "CPU Architecture": ["adb", "-s", device, "shell", "getprop", "ro.product.cpu.abi"],
            "Hardware": ["adb", "-s", device, "shell", "getprop", "ro.hardware"],
            "Storage": ["adb", "-s", device, "shell", "df", "-h", "/data"],
            "Total Memory": ["adb", "-s", device, "shell", "cat /proc/meminfo | grep MemTotal"],
            "Available Memory": [
                "adb",
                "-s",
                device,
                "shell",
                "cat /proc/meminfo | grep MemAvailable",
            ],
            "Resolution": ["adb", "-s", device, "shell", "wm", "size"],
            "Density": ["adb", "-s", device, "shell", "wm", "density"],
            "Timezone": ["adb", "-s", device, "shell", "getprop", "persist.sys.timezone"],
            "Mac": ["adb", "-s", device, "shell", "ip", "addr", "show", "wlan0"],
        }
        info = self._fetch_device_info(commands)
        info["device_ip"] = device
        info["ip"] = device  # 向后兼容旧 controller/UI 代码
        return info

    @async_command
    def get_devices_basic_info_async(self, device: str) -> dict[str, str]:
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Aversion": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
        }
        return self._fetch_device_info(commands)

    @staticmethod
    def get_devices_basic_info(device):
        """Synchronous wrapper used by DeviceStore for quick lookups."""
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Aversion": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
        }
        return ADBModelCore._fetch_device_info(commands)
