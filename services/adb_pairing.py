"""无线调试单轮配对协议；不依赖 Qt，不发布原始命令输出或配对秘密。"""

from __future__ import annotations

import io
import math
import os
import re
import secrets
import string
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol

import segno

from core.exec import CommandResult, CommandRunner
from utils.adb_targets import normalize_adb_connect_target

PairingMode = Literal["qr", "manual", "continue"]
PairingState = Literal[
    "Checking",
    "WaitingForScan",
    "Pairing",
    "WaitingForConnection",
    "Connected",
    "PairedOnly",
    "Failed",
    "Uncertain",
    "Idle",
    "CleanupFailed",
]
_PAIRING_TYPE = "_adb-tls-pairing._tcp"
_CONNECT_TYPE = "_adb-tls-connect._tcp"
_INSTANCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")
_MDNS_ERROR = re.compile(r"\b(?:disabled|unavailable|unsupported|error|unknown command)\b", re.I)
_UNSUPPORTED_PAIR = re.compile(
    r"^\s*(?:adb(?:\.exe)?:\s*)?(?:(?:usage|error):\s*)?"
    r"(?:unknown|unsupported) command[:\s]+['\"]?pair['\"]?\s*$",
    re.I | re.M,
)
_PREPARE_SECONDS = 15.0
_SCAN_SECONDS = 120.0
_PAIR_SECONDS = 15.0
_CONNECT_SECONDS = 30.0
_TOTAL_SECONDS = 180.0


@dataclass(frozen=True)
class PairingContext:
    """冻结单轮客户端、环境和代次；路径与环境仅供内部执行，不进入 repr。"""

    adb_path: str = field(repr=False)
    env: Mapping[str, str] = field(repr=False)
    context_revision: int

    def __post_init__(self) -> None:
        if not os.path.isabs(self.adb_path):
            raise ValueError("invalid_adb_path")
        snapshot = {key: value for key, value in self.env.items() if key.upper() != "ADB_TRACE"}
        object.__setattr__(self, "env", MappingProxyType(snapshot))


@dataclass(frozen=True)
class PairingContinuation:
    """仅保留已明确配对的身份和原上下文，不携带二维码或配对码。"""

    guid: str = field(repr=False)
    context: PairingContext = field(repr=False)

    @property
    def context_revision(self) -> int:
        """续连更换请求编号，但继续使用原配对环境代次。"""
        return self.context.context_revision


@dataclass(frozen=True)
class PairingRequest:
    """单轮输入；调用方必须在工作线程结束后释放请求与二维码引用。"""

    request_id: int
    mode: PairingMode
    pairing_endpoint: str = field(default="", repr=False)
    service_name: str = field(default="", repr=False)
    secret: str = field(default="", repr=False)
    connection_endpoint: str = field(default="", repr=False)
    continuation: PairingContinuation | None = field(default=None, repr=False)
    qr_scale: int = 6


@dataclass(frozen=True)
class PairingProgress:
    """可展示进度只包含固定状态、原因码和剩余秒数。"""

    request_id: int
    state: PairingState
    reason: str = ""
    remaining_seconds: int = 0


@dataclass(frozen=True)
class PairingOutcome:
    """内部完成结果；只有精确核实无线身份才允许 connected 为真。"""

    request_id: int
    context_revision: int
    paired: bool | None
    connected: bool
    reason: str
    state: PairingState
    guid: str = field(default="", repr=False)
    device_id: str = field(default="", repr=False)
    connection_endpoint: str = field(default="", repr=False)
    continuation: PairingContinuation | None = field(default=None, repr=False)


@dataclass(frozen=True)
class MdnsService:
    """经校验的发现记录，仅在服务内部参与精确身份关联。"""

    name: str = field(repr=False)
    service_type: str
    endpoint: str = field(repr=False)


class CommandScope(Protocol):
    """执行器已返回时仍存活的自有客户端必须阻止后续命令。"""

    def is_running(self) -> bool: ...


def create_qr_request(request_id: int, *, qr_scale: int = 6) -> PairingRequest:
    """为每轮生成独立 ASCII 服务名和口令，避免协议分隔符转义。"""
    alphabet = string.ascii_letters + string.digits
    return PairingRequest(
        request_id,
        "qr",
        service_name="studio-" + secrets.token_hex(10),
        secret="".join(secrets.choice(alphabet) for _ in range(24)),
        qr_scale=qr_scale,
    )


def create_manual_request(request_id: int, pairing_endpoint: str, code: str) -> PairingRequest:
    """手动入口只接受明确 IP 端口和 ASCII 六位码，保留前导零。"""
    endpoint, error = normalize_adb_connect_target(pairing_endpoint)
    if error or re.fullmatch(r"[0-9]{6}", code) is None:
        raise ValueError("invalid_request")
    return PairingRequest(request_id, "manual", pairing_endpoint=endpoint, secret=code)


def create_continuation_request(
    request_id: int,
    continuation: PairingContinuation,
    connection_endpoint: str,
) -> PairingRequest:
    """补填的是连接端口；此请求不会再次执行配对写操作。"""
    endpoint, error = normalize_adb_connect_target(connection_endpoint)
    if error:
        raise ValueError("invalid_request")
    return PairingRequest(
        request_id,
        "continue",
        connection_endpoint=endpoint,
        continuation=continuation,
    )


def parse_mdns_services(output: str) -> tuple[MdnsService, ...]:
    """只解析已知服务及合法地址；未知响应不能假装成正常空发现。"""
    rows: list[MdnsService] = []
    recognized = False
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().rstrip(":") == "list of discovered mdns services":
            recognized = True
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        name, service_type, address = parts
        service_type = service_type.rstrip(".")
        if service_type not in (_PAIRING_TYPE, _CONNECT_TYPE):
            continue
        instance = _instance_name(name, service_type)
        endpoint, error = normalize_adb_connect_target(address)
        if not instance or error:
            continue
        recognized = True
        row = MdnsService(instance, service_type, endpoint)
        if row not in rows:
            rows.append(row)
    # 明确后端错误必须优先于标题；其他诊断行不参与服务解析。
    if re.search(
        r"(?:^|\n)\s*(?:error:|.*\bmdns\b.*\b(?:disabled|unavailable|unsupported)\b)", output, re.I
    ):
        raise ValueError("mdns_unavailable")
    if not recognized:
        raise ValueError("mdns_unrecognized")
    return tuple(rows)


def _instance_name(value: str, service_type: str) -> str:
    """仅规范化已知服务后缀，GUID 本体的大小写和前缀保持原样。"""
    value = value.removesuffix(".")
    suffix = "." + service_type
    if value.endswith(suffix + ".local"):
        value = value[: -len(suffix + ".local")]
    elif value.endswith(suffix):
        value = value[: -len(suffix)]
    return value if _INSTANCE.fullmatch(value) else ""


def parse_pair_result(result: CommandResult) -> tuple[bool | None, str]:
    """配对正文决定明确成功/失败，未知格式不推断远端是否接受信任。"""
    body = result.output + "\n" + result.error
    if result.cancelled or result.timed_out:
        return None, ""
    if re.search(r"\b(?:failed(?: to)? pair(?:ing)?|pairing failed)\b", body, re.I):
        return False, ""
    match = re.search(
        r"^\s*(?:Enter pairing code:\s*)?Successfully paired to[ \t]+(\S+)"
        r"(?:[ \t]+\[guid=([^\]\r\n]+)\])?[ \t]*$",
        body,
        re.M,
    )
    if match is None or not result.success:
        return None, ""
    _, error = normalize_adb_connect_target(match.group(1))
    if error:
        return None, ""
    guid = match.group(2) or ""
    return True, guid if _INSTANCE.fullmatch(guid) else ""


class PairingService:
    """同步单轮服务；命令、单调时钟与可取消等待可注入供离线验证。"""

    def __init__(
        self,
        *,
        command_runner: Callable[..., CommandResult] = CommandRunner.run,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[threading.Event, float], bool] | None = None,
    ) -> None:
        self._command_runner = command_runner
        self._clock = clock
        self._wait = wait or (lambda event, seconds: event.wait(seconds))

    def run(
        self,
        request: PairingRequest,
        context: PairingContext,
        cancel_event: threading.Event,
        command_scope: CommandScope,
        on_progress: Callable[[PairingProgress], None],
        on_qr: Callable[[int, bytes, int, float], bool],
    ) -> PairingOutcome:
        """回调仅交付安全状态与内存 PNG；on_qr 须在传入预算内确认实际显示。"""
        session = _PairingSession(self, request, context, cancel_event, command_scope, on_progress)
        try:
            outcome = session.run(on_qr)
        except _Stop as stop:
            outcome = session.outcome(stop.state, stop.reason)
        on_progress(PairingProgress(request.request_id, outcome.state, outcome.reason))
        return outcome


class _Stop(Exception):
    """内部控制流只携带固定原因码，绝不包装原始异常或命令文本。"""

    def __init__(self, reason: str, state: PairingState = "Failed") -> None:
        super().__init__(reason)
        self.reason = reason
        self.state: PairingState = state


class _PairingSession:
    """单次调用私有状态；服务实例本身不缓存秘密、GUID 或命令结果。"""

    def __init__(
        self,
        service: PairingService,
        request: PairingRequest,
        context: PairingContext,
        cancelled: threading.Event,
        scope: CommandScope,
        progress: Callable[[PairingProgress], None],
    ) -> None:
        self.service = service
        self.request = request
        self.context = context
        self.cancelled = cancelled
        self.scope = scope
        self.progress = progress
        self.total_deadline = self.now() + _TOTAL_SECONDS
        self.deadline = min(self.total_deadline, self.now() + _PREPARE_SECONDS)
        self.state: PairingState = "Checking"
        self.paired: bool | None = None
        self.guid = ""
        self.endpoint = ""

    def now(self) -> float:
        return self.service._clock()

    def remaining(self) -> float:
        return max(0.0, min(self.deadline, self.total_deadline) - self.now())

    def check_stopped(self) -> None:
        if self.scope.is_running():
            raise _Stop("cleanup_failed", "CleanupFailed")
        if self.cancelled.is_set():
            raise _Stop("cancelled", "Idle")

    def check_budget(self) -> None:
        self.check_stopped()
        if self.remaining() > 0:
            return
        if self.state == "WaitingForConnection":
            raise _Stop("connection_timeout", "PairedOnly")
        if self.state == "WaitingForScan":
            raise _Stop("scan_timeout")
        if self.state == "Pairing":
            raise _Stop("pair_uncertain", "Uncertain")
        raise _Stop("prepare_timeout")

    def announce(self, state: PairingState, seconds: float) -> None:
        self.state = state
        self.deadline = min(self.total_deadline, self.now() + seconds)
        self.emit_progress()

    def emit_progress(self) -> None:
        self.progress(
            PairingProgress(
                self.request.request_id,
                self.state,
                remaining_seconds=math.ceil(self.remaining()),
            )
        )

    def command(
        self,
        args: list[str],
        *,
        seconds: float = 5.0,
        input_bytes: bytes | None = None,
    ) -> CommandResult:
        self.check_budget()
        try:
            result = self.service._command_runner(
                [self.context.adb_path, *args],
                timeout=min(seconds, self.remaining()),
                shell=False,
                native_only=True,
                cancelled=self.cancelled.is_set,
                input_bytes=input_bytes,
                env=dict(self.context.env),
                command_scope=self.scope,
            )
        except (OSError, RuntimeError, ValueError):
            self.check_stopped()
            if self.state == "Pairing":
                raise _Stop("pair_uncertain", "Uncertain") from None
            if self.state == "WaitingForConnection":
                # 写命令异常不证明服务器未接受请求，保留后续只读身份核验。
                return CommandResult(False, outcome="failed")
            raise _Stop("command_failed") from None
        self.check_stopped()
        if result.cancelled:
            raise _Stop("cancelled", "Idle")
        return result

    def pause(self) -> None:
        self.check_budget()
        self.service._wait(self.cancelled, min(1.0, self.remaining()))
        self.check_budget()
        self.emit_progress()

    def outcome(
        self,
        state: PairingState,
        reason: str = "",
        *,
        device_id: str = "",
    ) -> PairingOutcome:
        continuation = None
        if state == "PairedOnly" and self.guid:
            continuation = PairingContinuation(self.guid, self.context)
        return PairingOutcome(
            self.request.request_id,
            self.context.context_revision,
            self.paired,
            state == "Connected",
            reason,
            state,
            self.guid,
            device_id,
            self.endpoint,
            continuation,
        )

    def run(self, on_qr: Callable[[int, bytes, int, float], bool]) -> PairingOutcome:
        self.check_stopped()
        self.emit_progress()
        request = self.request
        if request.mode == "continue":
            continuation = request.continuation
            if continuation is None or not _INSTANCE.fullmatch(continuation.guid):
                raise _Stop("invalid_request")
            if continuation.context != self.context:
                raise _Stop("context_changed")
            endpoint, error = normalize_adb_connect_target(request.connection_endpoint)
            if error:
                raise _Stop("invalid_request")
            self.paired, self.guid, self.endpoint = True, continuation.guid, endpoint
            self.announce("WaitingForConnection", _CONNECT_SECONDS)
            self.command(["connect", endpoint], seconds=10.0)
            return self.confirm_connection(manual=True)
        if request.mode == "qr":
            if (
                not _INSTANCE.fullmatch(request.service_name)
                or re.fullmatch(r"[A-Za-z0-9]{24}", request.secret) is None
                or not 1 <= request.qr_scale <= 20
            ):
                raise _Stop("invalid_request")
            endpoint = self.discover_pairing(on_qr)
        elif request.mode == "manual":
            endpoint, error = normalize_adb_connect_target(request.pairing_endpoint)
            if error or re.fullmatch(r"[0-9]{6}", request.secret) is None:
                raise _Stop("invalid_request")
        else:
            raise _Stop("invalid_request")
        self.announce("Pairing", _PAIR_SECONDS)
        result = self.command(
            ["pair", endpoint],
            seconds=_PAIR_SECONDS,
            input_bytes=(request.secret + "\n").encode("ascii"),
        )
        if not result.timed_out and _UNSUPPORTED_PAIR.search(result.output + "\n" + result.error):
            self.paired = False
            raise _Stop("unsupported_client")
        self.paired, self.guid = parse_pair_result(result)
        # 结果正文可能回显秘密，配对阶段结束立即释放这一份引用。
        del result
        if self.paired is False:
            raise _Stop("pair_failed")
        if self.paired is None:
            raise _Stop("pair_uncertain", "Uncertain")
        if not self.guid:
            return self.outcome("PairedOnly", "guid_unavailable")
        self.announce("WaitingForConnection", _CONNECT_SECONDS)
        return self.confirm_connection(manual=False)

    def discover_pairing(self, on_qr: Callable[[int, bytes, int, float], bool]) -> str:
        result = self.command(["mdns", "check"])
        if result.timed_out:
            raise _Stop("mdns_timeout")
        if not result.success or _MDNS_ERROR.search(result.output + "\n" + result.error):
            raise _Stop("mdns_unavailable")
        if re.search(r"^mdns daemon version \[[^\]\r\n]+\]$", result.output.strip(), re.M) is None:
            raise _Stop("mdns_unrecognized")
        self.check_budget()
        payload = f"WIFI:T:ADB;S:{self.request.service_name};P:{self.request.secret};;"
        qr = segno.make_qr(payload)
        png = io.BytesIO()
        qr.save(png, kind="png", scale=self.request.qr_scale, border=4, dark="#000", light="#fff")
        module_count = int(qr.symbol_size(scale=1, border=4)[0])
        del payload, qr
        shown = on_qr(self.request.request_id, png.getvalue(), module_count, self.remaining())
        png.close()
        self.check_budget()
        if not shown:
            raise _Stop("cancelled", "Idle")
        self.announce("WaitingForScan", _SCAN_SECONDS)
        while True:
            result = self.command(["mdns", "services"])
            self.check_budget()
            services = self.mdns_result(result)
            endpoints = {
                row.endpoint
                for row in services
                if row.service_type == _PAIRING_TYPE and row.name == self.request.service_name
            }
            if len(endpoints) > 1:
                raise _Stop("service_conflict")
            if endpoints:
                return next(iter(endpoints))
            self.pause()

    @staticmethod
    def mdns_result(result: CommandResult) -> tuple[MdnsService, ...]:
        if result.timed_out:
            raise _Stop("mdns_timeout")
        if not result.success:
            raise _Stop("mdns_unavailable")
        try:
            return parse_mdns_services(result.output)
        except ValueError as exc:
            # 解析器仅抛固定原因码，其异常不包含输入正文。
            raise _Stop(str(exc)) from None

    def confirm_connection(self, *, manual: bool) -> PairingOutcome:
        attempted_connect = manual
        mdns_available = not manual
        while True:
            result = self.command(["devices"])
            self.check_budget()
            devices = _online_devices(result)
            expected = self.guid + "." + _CONNECT_TYPE
            for device in devices:
                if not manual and (
                    device.endswith("." + _CONNECT_TYPE)
                    or device.endswith("." + _CONNECT_TYPE + ".")
                    or device.endswith("." + _CONNECT_TYPE + ".local")
                    or device.endswith("." + _CONNECT_TYPE + ".local.")
                ):
                    if _instance_name(device, _CONNECT_TYPE) == self.guid:
                        return self.outcome("Connected", device_id=device)
            if mdns_available:
                mdns = self.command(["mdns", "services"])
                self.check_budget()
                try:
                    services = self.mdns_result(mdns)
                except _Stop:
                    # 手动配对不依赖发现后端；已配对身份仍可转补填地址。
                    mdns_available = False
                else:
                    endpoints = {
                        row.endpoint
                        for row in services
                        if row.service_type == _CONNECT_TYPE and row.name == self.guid
                    }
                    if len(endpoints) > 1:
                        raise _Stop("service_conflict", "PairedOnly")
                    if endpoints:
                        self.endpoint = next(iter(endpoints))
            if self.endpoint and self.endpoint in devices:
                result = self.command(
                    [
                        "-s",
                        self.endpoint,
                        "shell",
                        "getprop",
                        "persist.adb.wifi.guid",
                    ]
                )
                self.check_budget()
                if result.success and result.output.strip() == self.guid:
                    return self.outcome("Connected", device_id=self.endpoint)
                if result.success and result.output.strip():
                    raise _Stop("identity_mismatch", "PairedOnly")
            if self.endpoint and not attempted_connect:
                attempted_connect = True
                self.command(["connect", expected], seconds=10.0)
                # connect 结果只能触发只读确认，任何失败都不得自动重放写操作。
                continue
            self.pause()


def _online_devices(result: CommandResult) -> set[str]:
    if not result.success:
        return set()
    devices = set()
    for line in result.output.splitlines():
        columns = line.split()
        if len(columns) >= 2 and columns[1] == "device":
            devices.add(columns[0])
    return devices
