"""直接访问本地 ADB 服务的协议边界；连接独占、总超时、取消且不重放业务请求。"""

from __future__ import annotations

import io
import socket
import struct
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import BinaryIO

CancelCheck = Callable[[], bool]


class CommandCancelled(Exception):
    """调用方请求取消；与设备端命令失败分开处理。"""


@dataclass(frozen=True)
class ExecutionDiagnostics:
    """单次请求的失败快照；只保存固定原因、耗时和计数，不保存请求或响应内容。"""

    stage: str
    reason: str
    elapsed_ms: float
    stage_ms: float
    budget_ms: float
    errno: int | None = None
    winerror: int | None = None
    received_bytes: int = 0


@dataclass(frozen=True)
class ExecutionResult:
    """后端原始结果；kind 表示传输状态，非零 returncode 仍是完整的远端结果。"""

    stdout: bytes = b""
    stderr: bytes = b""
    returncode: int = 0
    kind: str = "completed"
    diagnostics: ExecutionDiagnostics | None = field(default=None, kw_only=True, compare=False)


class AdbError(Exception):
    """协议或服务错误；诊断不包含设备标识和原始服务输出。"""


class OutputError(AdbError):
    """本地输出失败，不应据此失效设备能力或切换后端。"""


class Connection:
    """拥有一次请求的连接；所有网络读写共享总超时，不重连或重放命令。"""

    def __init__(self, timeout: float, cancelled: CancelCheck | None = None):
        self.cancelled = cancelled
        self._started = time.monotonic()
        self.deadline = self._started + timeout
        self._budget_ms = timeout * 1000
        self._received_bytes = 0
        self._stage = "connect"
        self._stage_started = self._started
        with self._phase("connect"):
            self._check_cancelled()
            self.sock = socket.create_connection(("127.0.0.1", 5037), timeout=timeout)
        self._disable_nagle()

    @contextmanager
    def _phase(self, stage: str):
        """阶段内部只在最终失败时取样；取消轮询的短超时不离开阶段。"""
        self._stage = stage
        self._stage_started = time.monotonic()
        try:
            yield
        except (CommandCancelled, OSError, AdbError) as exc:
            if not hasattr(exc, "_adb_diagnostics"):
                reason = (
                    "cancelled"
                    if isinstance(exc, CommandCancelled)
                    else "timeout"
                    if isinstance(exc, TimeoutError)
                    else "connection_refused"
                    if isinstance(exc, ConnectionRefusedError)
                    else "os_error"
                    if isinstance(exc, OSError)
                    else "protocol_error"
                )
                self._diagnose(exc, reason)
            raise

    def _diagnose(self, exc: Exception, reason: str) -> Exception:
        """将无内容的快照附到原异常，保留所有公开异常分类与消费者行为。"""
        now = time.monotonic()
        exc._adb_diagnostics = ExecutionDiagnostics(  # type: ignore[attr-defined]
            stage=self._stage,
            reason=reason,
            elapsed_ms=max(0.0, now - self._started) * 1000,
            stage_ms=max(0.0, now - self._stage_started) * 1000,
            budget_ms=self._budget_ms,
            errno=exc.errno if isinstance(exc, OSError) else None,
            winerror=getattr(exc, "winerror", None) if isinstance(exc, OSError) else None,
            received_bytes=self._received_bytes,
        )
        return exc

    def _disable_nagle(self) -> None:
        """关闭 Nagle 合并：ADB 是小请求—小响应的往返协议，合并写会放大单条命令延迟。"""

        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            # 测试替身或平台不支持时保持默认行为，不影响命令执行。
            pass

    def close(self) -> None:
        """释放本地连接；不保证设备端已脱离会话的后台进程被终止。"""
        self.sock.close()

    def _check_cancelled(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise CommandCancelled

    def _set_timeout(self, *, polling: bool = False) -> None:
        self._check_cancelled()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        self.sock.settimeout(min(0.1, remaining) if polling and self.cancelled else remaining)

    def read(self, size: int) -> bytes:
        """读取完整帧；未收到退出帧前断开必须视为失败。"""
        return self._read(size, "shell_frame")

    def _read(self, size: int, stage: str) -> bytes:
        with self._phase(stage):
            data = bytearray()
            while len(data) < size:
                self._set_timeout(polling=True)
                try:
                    chunk = self.sock.recv(size - len(data))
                except TimeoutError:
                    self._check_cancelled()
                    if self.cancelled is None or time.monotonic() >= self.deadline:
                        raise
                    continue
                if not chunk:
                    raise self._diagnose(
                        AdbError("ADB connection closed before a complete response."), "eof"
                    )
                self._received_bytes += len(chunk)
                data.extend(chunk)
            return bytes(data)

    def send(self, data: bytes) -> None:
        """发送有总超时约束的数据，失败后不重试。"""
        with self._phase("send"):
            self._set_timeout()
            self.sock.sendall(data)

    def read_string(self) -> bytes:
        """读取 ADB 的四位十六进制长度及其内容。"""
        raw_size = self._read(4, "read_length")
        if any(c not in b"0123456789abcdefABCDEF" for c in raw_size):
            raise self._diagnose(AdbError("Invalid ADB response length."), "invalid_length")
        return self._read(int(raw_size, 16), "read_payload")

    def request(self, service: str) -> None:
        """请求服务并检查状态；只输出固定诊断，避免服务错误泄露设备标识。"""
        payload = service.encode("utf-8")
        if not payload or len(payload) > 65535 or b"\0" in payload:
            raise AdbError("Invalid or oversized ADB request.")
        self.send(f"{len(payload):04x}".encode("ascii") + payload)
        status = self._read(4, "read_status")
        if status == b"OKAY":
            return
        if status == b"FAIL":
            message = self.read_string().lower()
            for match, explanation in (
                (b"more than one", "Multiple devices: select one with -s SERIAL."),
                (b"unauthorized", "Device unauthorized: approve debugging on the device."),
                (b"offline", "Device is offline."),
                (b"not found", "Selected device was not found."),
                (b"no devices", "No device is available."),
            ):
                if match in message:
                    raise self._diagnose(AdbError(explanation), "server_fail")
            raise self._diagnose(
                AdbError("ADB rejected the request; check device state and shell v2 support."),
                "server_fail",
            )
        raise self._diagnose(AdbError("Invalid ADB response status."), "invalid_status")


def execute(
    command: str,
    args: list[str],
    *,
    serial: str | None,
    timeout: float,
    stdout: BinaryIO,
    stderr: BinaryIO,
    cancelled: CancelCheck | None = None,
) -> int:
    """执行已验证参数并流式返回输出和远端退出码；不接收 stdin 或分配终端。"""
    connection = Connection(timeout, cancelled)
    try:
        if command not in {"devices", "shell"}:
            raise AdbError("Unsupported command.")
        if command == "devices":
            connection.request("host:devices-l" if args else "host:devices")
            stdout.write(b"List of devices attached\n" + connection.read_string() + b"\n")
            stdout.flush()
            return 0
        connection.request("host:transport:" + serial if serial else "host:transport-any")
        # 与原生 adb shell 一样用空格拼接参数；调用方负责远端 shell 的 quote 边界。
        connection.request("shell,v2,raw:" + " ".join(args))
        connection.send(struct.pack("<BI", 4, 0))
        while True:
            channel, size = struct.unpack("<BI", connection.read(5))
            if channel not in (1, 2, 3) or size > 1024 * 1024:
                raise connection._diagnose(AdbError("Invalid shell v2 frame."), "invalid_frame")
            if channel == 3 and size != 1:
                raise connection._diagnose(
                    AdbError("Invalid shell v2 exit status."), "invalid_frame"
                )
            data = connection.read(size)
            if channel == 3:
                return data[0]
            stream = stdout if channel == 1 else stderr
            try:
                stream.write(data)
                stream.flush()
            except OSError as exc:
                raise OutputError("Unable to write ADB output.") from exc
    except ConnectionRefusedError as exc:
        error = AdbError("ADB connection failed after request admission.")
        error._adb_diagnostics = getattr(exc, "_adb_diagnostics", None)  # type: ignore[attr-defined]
        raise error from exc
    finally:
        connection.close()


def capture(
    command: str,
    args: list[str],
    *,
    serial: str | None,
    timeout: float,
    cancelled: CancelCheck | None = None,
    stdout_sink: BinaryIO | None = None,
) -> ExecutionResult:
    """捕获双流或流式写入调用方拥有的输出；仅连接被拒绝允许发送前回退。"""
    stdout = stdout_sink if stdout_sink is not None else io.BytesIO()
    stderr = io.BytesIO()
    try:
        code = execute(
            command,
            args,
            serial=serial,
            timeout=timeout,
            stdout=stdout,
            stderr=stderr,
            cancelled=cancelled,
        )
        output = (
            stdout.getvalue() if isinstance(stdout, io.BytesIO) and stdout_sink is None else b""
        )
        return ExecutionResult(output, stderr.getvalue(), code)
    except ConnectionRefusedError as exc:
        return ExecutionResult(
            kind="unavailable", diagnostics=getattr(exc, "_adb_diagnostics", None)
        )
    except CommandCancelled as exc:
        return ExecutionResult(kind="cancelled", diagnostics=getattr(exc, "_adb_diagnostics", None))
    except TimeoutError as exc:
        return ExecutionResult(kind="timeout", diagnostics=getattr(exc, "_adb_diagnostics", None))
    except OutputError as exc:
        return ExecutionResult(
            stderr=str(exc).encode("utf-8"),
            kind="output",
            diagnostics=getattr(exc, "_adb_diagnostics", None),
        )
    except AdbError as exc:
        return ExecutionResult(
            stderr=str(exc).encode("utf-8"),
            kind="protocol",
            diagnostics=getattr(exc, "_adb_diagnostics", None),
        )
    except OSError as exc:
        return ExecutionResult(
            stderr=b"ADB connection failed",
            kind="transport",
            diagnostics=getattr(exc, "_adb_diagnostics", None),
        )
