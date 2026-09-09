"""scrcpy 会话身份、helper 租约与精确隧道清理；不改变 ADB 服务生命周期。"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from core.adb_transport import Connection
from core.scrcpy_adb_protocol import ScrcpyAdbProtocol


def session_configuration(
    environment: Mapping[str, str],
) -> tuple[str, Path, int, tuple[int, int], Path]:
    """解析启动时冻结的可信配置；诊断只包含固定信息，不回显目标或本机路径。"""
    serial = environment.get("ADBLAB_SCRCPY_SERIAL", "")
    raw_server = environment.get("ADBLAB_SCRCPY_SERVER", "")
    raw_session = environment.get("ADBLAB_SCRCPY_SESSION_FILE", "")
    raw_owner = environment.get("ADBLAB_SCRCPY_OWNER_PID", "")
    raw_ports = environment.get("ADBLAB_SCRCPY_PORT_RANGE", "")
    if not re.fullmatch(r"[1-9][0-9]{0,9}", raw_owner) or int(raw_owner) <= 1:
        raise ValueError("A live scrcpy owner process is required.")
    if not re.fullmatch(r"[0-9]{1,5}:[0-9]{1,5}", raw_ports):
        raise ValueError("A fixed scrcpy port range is required.")
    first, last = (int(item) for item in raw_ports.split(":"))
    server, session = Path(raw_server), Path(raw_session)
    if not server.is_absolute() or not server.is_file():
        raise ValueError("A trusted scrcpy server file is required.")
    if not session.is_absolute() or not session.parent.is_dir():
        raise ValueError("A private scrcpy session directory is required.")
    # 构造时校验 serial、端口和固定文件；此处不接触网络或创建会话状态。
    ScrcpyAdbProtocol(
        serial, server, scid="00000000", port_range=(first, last),
        session_token=session_token(session),
    )
    return serial, server.resolve(), int(raw_owner), (first, last), session


def session_token(session_file: Path) -> str:
    """从启动时创建的随机私有目录派生文件身份，不暴露设备标识或本机路径。"""
    normalized = os.path.normcase(str(session_file.resolve()))
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _identity(serial: str, server: Path, owner: int, ports: tuple[int, int], path: Path) -> str:
    return hashlib.sha256(
        json.dumps(
            [serial, str(server), owner, ports, session_token(path)],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def mark_server_pending(environment: Mapping[str, str]) -> None:
    """已验证的上传在 SEND 前登记身份，使部分上传和隧道建立前失败也能精确清理。"""
    serial, server, owner, ports, path = session_configuration(environment)
    identity = _identity(serial, server, owner, ports, path)
    pending = path.with_name("server.pending")
    try:
        with pending.open("x", encoding="ascii") as destination:
            destination.write(identity)
    except FileExistsError:
        _check_pending(pending, identity)


def _check_pending(pending: Path, identity: str) -> None:
    with pending.open("rb") as source:
        if source.read(65) != identity.encode("ascii"):
            raise ValueError("Scrcpy server upload belongs to another launch.")


def session_scid(environment: Mapping[str, str], command: str, args: list[str]) -> str:
    """首个合法隧道创建原子绑定 scid；清理和 shell 只能使用已绑定的独立会话。"""
    serial, server, owner, ports, path = session_configuration(environment)
    identity = _identity(serial, server, owner, ports, path)

    def validate(scid: str) -> None:
        ScrcpyAdbProtocol(
            serial, server, scid=scid, port_range=ports, session_token=session_token(path),
        ).validate(command, args)

    def read_existing() -> str:
        with path.open("rb") as source:
            raw = source.read(4097)
        try:
            state = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid scrcpy session state.") from exc
        if not isinstance(state, dict) or state.get("identity") != identity:
            raise ValueError("Scrcpy session state belongs to another launch.")
        scid = state.get("scid")
        if not isinstance(scid, str):
            raise ValueError("Invalid scrcpy session identifier.")
        validate(scid)
        return scid

    try:
        return read_existing()
    except FileNotFoundError:
        if command in {"start-server", "devices", "push"}:
            validate("00000000")
            return "00000000"
        if command not in {"forward", "reverse"} or len(args) != 2 or args[0] == "--remove":
            raise ValueError("Scrcpy session must start with its own tunnel.") from None
        endpoint = args[1] if command == "forward" else args[0]
        match = re.fullmatch(r"localabstract:scrcpy_([0-9a-f]{8})", endpoint)
        if not match:
            raise ValueError("Invalid scrcpy tunnel identifier.") from None
        scid = match.group(1)
        validate(scid)
        try:
            with path.open("x", encoding="utf-8") as destination:
                json.dump({"identity": identity, "scid": scid}, destination)
        except FileExistsError:
            # 并发准入只能接受已建立的同一身份，不覆盖已出现的会话文件。
            return read_existing()
        return scid


def _lock(lease: BinaryIO) -> bool:
    lease.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return False
        raise


@contextmanager
def helper_lease(session_file: Path) -> Iterator[None]:
    """持有当前 helper 的独立文件锁；正常退出删租约，强退由 OS 自动释放锁。"""
    path = session_file.parent / f"helper-{os.getpid()}-{uuid.uuid4().hex}.lease"
    try:
        with path.open("x+b") as lease:
            lease.write(b"1")
            lease.flush()
            if not _lock(lease):
                raise OSError("Unable to acquire scrcpy helper lease.")
            yield
    finally:
        path.unlink(missing_ok=True)


def has_active_helpers(session_file: Path) -> bool:
    """只读判断目录内是否仍有持锁 helper；不能打开的租约保留为明确失败。"""
    for path in session_file.parent.glob("helper-*.lease"):
        try:
            with path.open("r+b") as lease:
                if not _lock(lease):
                    return True
        except FileNotFoundError:
            continue
    return False


def cleanup_session_tunnels(environment: Mapping[str, str], timeout: float = 3.0) -> None:
    """总时限内删除本会话的已确认映射和待清理 JAR；断线、身份冲突或超时均失败。"""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid scrcpy cleanup timeout.")
    serial, server, owner, ports, path = session_configuration(environment)
    pending = path.with_name("server.pending")
    has_server = pending.exists()
    if has_server:
        _check_pending(pending, _identity(serial, server, owner, ports, path))
    has_tunnels = path.exists()
    if not has_tunnels and not has_server:
        # 隧道与上传在请求发送前分别落盘；未准入任何写操作时不新增清理 I/O。
        return
    scid = session_scid(environment, "devices", []) if has_tunnels else "00000000"
    socket_name = "localabstract:scrcpy_" + scid
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("Scrcpy tunnel cleanup timed out.")
        return value

    def cancelled() -> bool:
        remaining()
        return False

    def query(service: str, *, device: bool = False) -> list[list[bytes]]:
        connection = Connection(remaining(), cancelled)
        try:
            if device:
                connection.request("host:transport:" + serial)
            connection.request(service)
            return [line.split() for line in connection.read_string().splitlines()]
        finally:
            connection.close()

    forwards = query("host:list-forward") if has_tunnels else []
    reverses = query("reverse:list-forward", device=True) if has_tunnels else []
    operations: list[tuple[str, list[str]]] = []
    for entry in forwards:
        if len(entry) == 3 and entry[0] == serial.encode() and entry[2] == socket_name.encode():
            operations.append(("forward", ["--remove", entry[1].decode("ascii")]))
    if any(len(entry) == 3 and entry[1] == socket_name.encode() for entry in reverses):
        operations.append(("reverse", ["--remove", socket_name]))
    for command, args in operations:
        protocol = ScrcpyAdbProtocol(
            serial,
            server,
            scid=scid,
            port_range=ports,
            session_token=session_token(path),
            timeout=remaining(),
            cancelled=cancelled,
        )
        protocol.execute(command, args, stdout=io.BytesIO(), stderr=io.BytesIO())
    if has_server:
        ScrcpyAdbProtocol(
            serial, server, scid=scid, port_range=ports, session_token=session_token(path),
            timeout=remaining(), cancelled=cancelled,
        ).cleanup_server()
