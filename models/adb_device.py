"""
Device connection, discovery, and info retrieval.

Imports only from adb_model (core) — no circular dependencies.
"""

import subprocess
import time

from .adb_model import ADBModelCore, async_command


class ADBDevice(ADBModelCore):
    """Device management: connect, disconnect, restart, and info queries."""

    @async_command
    def connect_device_async(self, ip_address: str):
        return self._execute_command(["adb", "connect", ip_address])

    @async_command
    def get_connected_devices_async(self):
        r = self._exec(["adb", "devices"])
        if not r["ok"]:
            return []
        return [line.split("\t")[0] for line in r["data"].strip().splitlines()[1:] if "device" in line]

    @async_command
    def disconnect_device_async(self, device: str) -> dict:
        try:
            result = self._execute_command(["adb", "disconnect", device])
            return {"ip": device, "raw_result": result, "success": "disconnected" in result.lower()}
        except Exception as e:
            return {"ip": device, "raw_result": str(e), "success": False}

    @async_command
    def restart_device_async(self, device: str) -> dict:
        try:
            check_result = self._execute_command(["adb", "-s", device, "get-state"])
            if "device" not in check_result:
                return {
                    "ip": device,
                    "success": False,
                    "error": f"Abnormal device status: {check_result.strip()}",
                    "requires_refresh": False,
                }
            result = self._execute_command(["adb", "-s", device, "reboot"], timeout=3)
            return {
                "ip": device,
                "success": False,
                "error": f"abnormal return: {result}",
                "requires_refresh": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "ip": device,
                "success": True,
                "requires_refresh": True,
                "raw_result": "The device is starting to restart",
            }
        except Exception as e:
            return {"ip": device, "success": False, "error": str(e), "requires_refresh": False}

    @async_command
    def restart_adb_async(self) -> dict:
        try:
            self._execute_command(["adb", "kill-server"])
            time.sleep(1)
            self._execute_command(["adb", "start-server"], timeout=5)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
        info["ip"] = device
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
