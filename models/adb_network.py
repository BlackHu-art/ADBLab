"""
ADB Network Mixin — port forwarding, reverse, TCP/IP, wireless pairing, ping, netstat.

Compose with ADBModelCore subclass (e.g. ADBAdvanced). All methods are @async_command.
"""

from .adb_model import async_command
from utils.adb_resolver import CF


class ADBNetworkMixin:
    """Mixin providing network-related ADB operations."""

    # ── Port Forwarding ──────────────────────────────────────────────────

    @async_command
    def forward_port_async(
        self, device_ip: str, local_port: str, remote_port: str, protocol: str = "tcp"
    ) -> dict:
        try:
            spec = f"{protocol}:{local_port}"
            remote_spec = f"{protocol}:{remote_port}"
            result = self._execute_command(["adb", "-s", device_ip, "forward", spec, remote_spec])
            return {
                "success": True, "device_ip": device_ip, "output": result,
                "local": spec, "remote": remote_spec,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def list_forwards_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "forward", "--list"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def remove_forward_async(self, device_ip: str, local_spec: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "forward", "--remove", local_spec]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def remove_all_forwards_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "forward", "--remove-all"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def reverse_port_async(
        self, device_ip: str, remote_port: str, local_port: str, protocol: str = "tcp"
    ) -> dict:
        try:
            spec = f"{protocol}:{remote_port}"
            local_spec = f"{protocol}:{local_port}"
            result = self._execute_command(["adb", "-s", device_ip, "reverse", spec, local_spec])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def list_reverse_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "reverse", "--list"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def remove_all_reverse_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "reverse", "--remove-all"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Wireless Debugging ──────────────────────────────────────────────

    @async_command
    def tcpip_mode_async(self, device_ip: str, port: str = "5555") -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "tcpip", port])
            return {"success": True, "device_ip": device_ip, "port": port, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pair_device_async(self, ip_address: str, port: str, pairing_code: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "pair", f"{ip_address}:{port}", pairing_code], timeout=15
            )
            return {"success": True, "ip": ip_address, "output": result}
        except Exception as e:
            return {"success": False, "ip": ip_address, "error": str(e)}

    # ── Network ─────────────────────────────────────────────────────────

    @async_command
    def shell_ping_async(self, device_ip: str, host: str, count: str = "4") -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "ping", "-c", count, host], timeout=30
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def shell_netstat_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "netstat"], timeout=10)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}
