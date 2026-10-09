"""为运行中的本机 ADB 服务补注册后来启动的标准端口模拟器。"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

import psutil

from core.adb_transport import (
    CancelCheck,
    CommandCancelled,
    Connection,
    ExecutionResult,
    capture,
)

_EMULATOR_SERIAL = re.compile(rb"emulator-([0-9]+)")
_LOCAL_TCP_SERIAL = re.compile(rb"(?:127\.0\.0\.1|localhost|\[::1\]):([0-9]+)")


def _listening_emulator_ports() -> set[int]:
    """只枚举一次本机 IPv4 监听表，不连接候选端口或探测进程身份。"""
    ports: set[int] = set()
    for connection in psutil.net_connections(kind="tcp4"):
        address = connection.laddr
        if (
            connection.status == psutil.CONN_LISTEN and address
            and address.ip in {"127.0.0.1", "0.0.0.0"}
            and 5555 <= address.port <= 5585 and address.port % 2 == 1
        ):
            ports.add(address.port)
    return ports


def _valid_listing(listing: ExecutionResult) -> bool:
    """只有完整成功的设备列表可以作为补注册和最终返回的依据。"""
    lines = listing.stdout.lstrip().splitlines()
    return (
        listing.kind == "completed" and listing.returncode == 0
        and bool(lines) and lines[0] == b"List of devices attached"
    )


def _listed_ports(listing: ExecutionResult, *, settled_only: bool = False) -> set[int]:
    """初始去重接受任何状态；补注册后的确认仅接受在线或等待用户授权的稳定状态。"""
    ports: set[int] = set()
    for line in listing.stdout.splitlines():
        fields = line.split()
        if len(fields) < 2 or (settled_only and fields[1] not in {b"device", b"unauthorized"}):
            continue
        emulator = _EMULATOR_SERIAL.fullmatch(fields[0])
        if emulator is not None:
            ports.add(int(emulator[1]) + 1)
        else:
            local_tcp = _LOCAL_TCP_SERIAL.fullmatch(fields[0])
            if local_tcp is not None:
                ports.add(int(local_tcp[1]))
    return ports


def recover_local_emulators(
    listing: ExecutionResult,
    *,
    timeout: float,
    cancelled: CancelCheck | None = None,
    diagnostic: Callable[[str], None] = lambda _message: None,
) -> ExecutionResult:
    """在共享预算内补注册本机模拟器，失败保留最近一次可信列表，取消单独返回。

    调用方仅在后台探测默认本机服务时使用；显式 ADBHOST 会改变服务连接目标，
    因此额外拒绝补注册。监听快照不可中断，返回后必须再次检查截止时间和取消。
    通知没有 ACK，不代表设备在线；不重放通知、不创建客户端，也不重启共享服务。
    """
    deadline = time.monotonic() + max(0.0, timeout)

    def stopped() -> bool:
        """所有可能启动下一步工作的边界共用取消检查。"""
        return cancelled is not None and cancelled()

    if stopped():
        return ExecutionResult(kind="cancelled")
    if not _valid_listing(listing) or os.environ.get("ADBHOST") or time.monotonic() >= deadline:
        return listing
    try:
        ports = _listening_emulator_ports() - _listed_ports(listing)
    except (psutil.Error, OSError):
        diagnostic("ADB emulator discovery status=listener_snapshot_failed")
        return ExecutionResult(kind="cancelled") if stopped() else listing
    if stopped():
        return ExecutionResult(kind="cancelled")

    notified: set[int] = set()
    for port in sorted(ports):
        if stopped():
            return ExecutionResult(kind="cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return listing
        try:
            connection = Connection(remaining, cancelled, connect_timeout=min(0.1, remaining))
            try:
                payload = f"host:emulator:{port}".encode("ascii")
                # host:emulator 无响应，不能使用会等待 OKAY 的 request()。
                connection.send(f"{len(payload):04x}".encode("ascii") + payload)
                notified.add(port)
            finally:
                connection.close()
        except CommandCancelled:
            return ExecutionResult(kind="cancelled")
        except OSError:
            diagnostic("ADB emulator discovery status=notification_failed")

    verification_failed = False
    while notified:
        if stopped():
            return ExecutionResult(kind="cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        checked = capture(
            "devices", ["-l"], serial=None, timeout=min(0.2, remaining), cancelled=cancelled,
        )
        if stopped() or checked.kind == "cancelled":
            return ExecutionResult(kind="cancelled")
        if _valid_listing(checked):
            listing = checked
            # 新 transport 先显示 offline 时继续等握手，避免当前刷新过早返回空在线列表。
            notified.difference_update(_listed_ports(checked, settled_only=True))
        elif not verification_failed:
            diagnostic("ADB emulator discovery status=verification_failed")
            verification_failed = True
        remaining = deadline - time.monotonic()
        if notified and remaining > 0:
            # 短间隔只等待服务提交新 transport，取消最多延后一个等待片段。
            time.sleep(min(0.05, remaining))
    return ExecutionResult(kind="cancelled") if stopped() else listing
