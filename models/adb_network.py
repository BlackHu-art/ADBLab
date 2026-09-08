"""提供端口映射（forward/reverse）与无线调试（tcpip/pair）等 ADB 网络操作。

该 mixin 应与 ADBModelCore 子类组合使用，公开操作均通过 @async_command 异步执行。
"""

from typing import Any

from utils.adb_values import normalize_tcp_port

from .adb_model import async_command


class ADBNetworkMixin:
    """封装网络相关的 ADB 操作；与 ADBModelCore 组合后提供 _run 执行入口。"""

    _run: Any

    # 端口正向与反向映射

    @async_command
    def forward_port_async(
        self, device_ip: str, local_port: str, remote_port: str, protocol: str = "tcp"
    ) -> dict:
        spec = f"{protocol}:{local_port}"
        remote_spec = f"{protocol}:{remote_port}"
        return self._run(
            ["adb", "-s", device_ip, "forward", "--no-rebind", spec, remote_spec],
            device_ip=device_ip,
            local=spec,
            remote=remote_spec,
        )

    @async_command
    def list_forwards_async(self, device_ip: str) -> dict:
        return self._device_forward_rules(device_ip)

    def _device_forward_rules(self, device_ip: str) -> dict:
        """正向映射属于本机 ADB server；按精确设备身份过滤，格式异常时拒绝继续删除。"""
        result = self._run(["adb", "forward", "--list"], device_ip=device_ip)
        if not result.get("success"):
            return result
        rules = []
        for line in str(result.get("output", "")).splitlines():
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != 3:
                return {**result, "success": False, "error": "Invalid ADB forward list response"}
            if fields[0] == device_ip:
                rules.append(" ".join(fields))
        return {**result, "output": "\n".join(rules)}

    @async_command
    def remove_all_forwards_async(self, device_ip: str) -> dict:
        """只移除该设备的规则，禁止调用会清空其他设备映射的 server 级 remove-all。"""
        result = self._device_forward_rules(device_ip)
        if not result.get("success"):
            return result
        removed = 0
        for line in result["output"].splitlines():
            local = line.split()[1]
            deletion = self._run(
                ["adb", "-s", device_ip, "forward", "--remove", local], device_ip=device_ip,
            )
            if not deletion.get("success"):
                return {**deletion, "output": f"Removed {removed} forward rule(s) before failure"}
            removed += 1
        return {**result, "output": f"Removed {removed} forward rule(s)"}

    @async_command
    def reverse_port_async(
        self, device_ip: str, remote_port: str, local_port: str, protocol: str = "tcp"
    ) -> dict:
        spec = f"{protocol}:{remote_port}"
        local_spec = f"{protocol}:{local_port}"
        return self._run(
            ["adb", "-s", device_ip, "reverse", spec, local_spec],
            device_ip=device_ip,
        )

    @async_command
    def list_reverse_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "reverse", "--list"],
            device_ip=device_ip,
        )

    @async_command
    def remove_all_reverse_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "reverse", "--remove-all"],
            device_ip=device_ip,
        )

    # 无线调试

    @async_command
    def tcpip_mode_async(self, device_ip: str, port: str = "5555") -> dict:
        try:
            port = normalize_tcp_port(port)
        except ValueError as exc:
            return {"success": False, "device_ip": device_ip, "error": str(exc)}
        return self._run(
            ["adb", "-s", device_ip, "tcpip", port],
            device_ip=device_ip,
            port=port,
        )

    @async_command
    def pair_device_async(self, ip_address: str, port: str, pairing_code: str) -> dict:
        if not ip_address.strip():
            return {"success": False, "ip": ip_address, "error": "IP address cannot be empty"}
        try:
            port = normalize_tcp_port(port)
        except ValueError as exc:
            return {"success": False, "ip": ip_address, "error": str(exc)}
        return self._run(
            ["adb", "pair", f"{ip_address}:{port}", pairing_code],
            timeout=15,
            ip=ip_address,
        )
