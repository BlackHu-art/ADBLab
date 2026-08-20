"""提供端口映射、无线调试、Ping 和网络状态等 ADB 网络操作。

该 mixin 应与 ADBModelCore 子类组合使用，公开操作均通过 @async_command 异步执行。
"""

from typing import Any

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
            ["adb", "-s", device_ip, "forward", spec, remote_spec],
            device_ip=device_ip,
            local=spec,
            remote=remote_spec,
        )

    @async_command
    def list_forwards_async(self, device_ip: str) -> dict:
        return self._run(["adb", "forward", "--list"], device_ip=device_ip)

    @async_command
    def remove_forward_async(self, device_ip: str, local_spec: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "forward", "--remove", local_spec],
            device_ip=device_ip,
        )

    @async_command
    def remove_all_forwards_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "forward", "--remove-all"],
            device_ip=device_ip,
        )

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
        return self._run(
            ["adb", "-s", device_ip, "tcpip", port],
            device_ip=device_ip,
            port=port,
        )

    @async_command
    def pair_device_async(self, ip_address: str, port: str, pairing_code: str) -> dict:
        return self._run(
            ["adb", "pair", f"{ip_address}:{port}", pairing_code],
            timeout=15,
            ip=ip_address,
        )

    # 网络诊断

    @async_command
    def shell_ping_async(self, device_ip: str, host: str, count: str = "4") -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ping", "-c", count, host],
            timeout=30,
            device_ip=device_ip,
        )

    @async_command
    def shell_netstat_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "netstat"],
            timeout=10,
            device_ip=device_ip,
        )
