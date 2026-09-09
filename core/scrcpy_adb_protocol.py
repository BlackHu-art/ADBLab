"""scrcpy 4.1 专用 ADB 服务协议；固定目标与服务端文件，业务请求失败后不重放。"""

from __future__ import annotations

import io
import math
import os
import re
import stat
import struct
from pathlib import Path
from typing import BinaryIO

from core.adb_transport import AdbError, CancelCheck, Connection, OutputError

SERVER_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"
SERVER_VERSION = "4.1"
_SHELL_PREFIX = [
    "CLASSPATH=" + SERVER_REMOTE_PATH,
    "app_process",
    "/",
    "com.genymobile.scrcpy.Server",
    SERVER_VERSION,
]
_SERVER_OPTIONS = frozenset(
    "scid log_level video video_bit_rate audio audio_bit_rate video_codec audio_codec "
    "video_source audio_source audio_dup max_size max_fps min_size_alignment angle "
    "capture_orientation tunnel_forward crop control display_id camera_id camera_size "
    "camera_facing camera_ar camera_fps camera_high_speed camera_torch camera_zoom "
    "show_touches stay_awake screen_off_timeout video_codec_options audio_codec_options "
    "video_encoder audio_encoder power_off_on_close clipboard_autosync downsize_on_error "
    "cleanup power_on new_display flex_display ignore_video_encoder_constraints "
    "display_ime_policy vd_destroy_content vd_system_decorations keep_active list_encoders "
    "list_displays list_cameras list_camera_sizes list_apps".split()
)


def host_version(*, timeout: float = 3.0, cancelled: CancelCheck | None = None) -> int:
    """只读检查已有本机服务；不会启动、杀死或替换 ADB 服务。"""
    _validate_timeout(timeout)
    connection = Connection(timeout, cancelled)
    try:
        connection.request("host:version")
        version = connection.read_string()
        if not re.fullmatch(rb"[0-9a-fA-F]{4}", version) or int(version, 16) == 0:
            raise AdbError("Invalid ADB server version.")
        return int(version, 16)
    finally:
        connection.close()


def _validate_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid scrcpy ADB timeout.")


def _write(stream: BinaryIO, data: bytes) -> None:
    try:
        stream.write(data)
        stream.flush()
    except OSError as exc:
        raise OutputError("Unable to write scrcpy ADB output.") from exc


def _read_status(connection: Connection) -> None:
    # forward/reverse 的服务准入成功后，还必须确认设备或服务端的实际映射结果。
    status = connection.read(4)
    if status == b"OKAY":
        return
    if status == b"FAIL":
        connection.read_string()
        raise AdbError("ADB tunnel operation failed.")
    raise AdbError("Invalid ADB tunnel response.")


class ScrcpyAdbProtocol:
    """为单个 scrcpy 会话提供有限操作；目标、端口范围和 scid 在创建时固定。"""

    def __init__(
        self,
        serial: str,
        server_path: str | Path,
        *,
        scid: str,
        port_range: tuple[int, int],
        session_token: str,
        timeout: float = 10.0,
        cancelled: CancelCheck | None = None,
    ):
        if not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]{1,255}", serial):
            raise ValueError("Invalid scrcpy device selector.")
        if not re.fullmatch(r"[0-9a-f]{8}", scid):
            raise ValueError("Invalid scrcpy session identifier.")
        if not re.fullmatch(r"[0-9a-f]{32}", session_token):
            raise ValueError("Invalid scrcpy private server identifier.")
        if not (1 <= port_range[0] <= port_range[1] <= 65535):
            raise ValueError("Invalid scrcpy port range.")
        _validate_timeout(timeout)
        self.serial = serial
        self.server_path = Path(server_path).resolve()
        self.scid = scid
        self.port_range = port_range
        self.timeout = timeout
        self.cancelled = cancelled
        self.socket_name = "localabstract:scrcpy_" + scid
        self.remote_server = f"/data/local/tmp/adblab-scrcpy-{session_token}.jar"

    def _port(self, endpoint: str) -> None:
        if not re.fullmatch(r"tcp:[0-9]{1,5}", endpoint):
            raise ValueError("Unsupported scrcpy TCP endpoint.")
        port = int(endpoint[4:])
        if not self.port_range[0] <= port <= self.port_range[1] or endpoint != f"tcp:{port}":
            raise ValueError("TCP endpoint is outside this scrcpy session.")

    def validate(self, command: str, args: list[str]) -> None:
        """发送前完成命令校验；不接受交互 shell、任意文件传输或跨会话清理。"""
        if command == "start-server" and not args:
            return
        if command == "devices" and args in ([], ["-l"]):
            return
        if command == "push" and len(args) == 2 and args[1] == SERVER_REMOTE_PATH:
            if Path(args[0]).resolve() != self.server_path:
                raise ValueError("Only the configured scrcpy server may be transferred.")
            if not self.server_path.is_file():
                raise ValueError("Configured scrcpy server is not a regular file.")
            return
        if command == "shell" and args[:5] == _SHELL_PREFIX:
            seen = set()
            for arg in args[5:]:
                key, separator, value = arg.partition("=")
                if (
                    not separator
                    or key not in _SERVER_OPTIONS
                    or key in seen
                    or not re.fullmatch(r"[A-Za-z0-9_./:@,+=%-]{0,4096}", value)
                ):
                    raise ValueError("Unsupported scrcpy server parameter.")
                if key == "scid" and value != self.scid:
                    raise ValueError("Server command belongs to another scrcpy session.")
                seen.add(key)
            if "scid" not in seen:
                raise ValueError("Server command has no scrcpy session identifier.")
            return
        if command in {"forward", "reverse"} and len(args) == 2:
            if args[0] == "--remove":
                if command == "forward":
                    self._port(args[1])
                elif args[1] != self.socket_name:
                    raise ValueError("Tunnel belongs to another scrcpy session.")
                return
            local, remote = args if command == "forward" else (args[1], args[0])
            self._port(local)
            if remote != self.socket_name:
                raise ValueError("Tunnel belongs to another scrcpy session.")
            return
        raise ValueError("Unsupported scrcpy ADB command.")

    def execute(
        self,
        command: str,
        args: list[str],
        *,
        stdout: BinaryIO,
        stderr: BinaryIO,
    ) -> int:
        """执行一次已限定操作；连接独占，shell 握手有时限、运行持续到退出或取消。"""
        self.validate(command, args)
        if command == "start-server":
            host_version(timeout=self.timeout, cancelled=self.cancelled)
            return 0
        if command == "forward" and args[0] == "--remove":
            self._check_forward_owner(args[1])
        connection = Connection(self.timeout, self.cancelled)
        try:
            if command == "devices":
                connection.request("host:devices-l" if args else "host:devices")
                _write(stdout, b"List of devices attached\n" + connection.read_string() + b"\n")
                return 0
            if command == "forward":
                operation = (
                    "killforward:" + args[1]
                    if args[0] == "--remove"
                    else ("forward:norebind:" + args[0] + ";" + args[1])
                )
                connection.request("host-serial:" + self.serial + ":" + operation)
                _read_status(connection)
                return 0
            connection.request("host:transport:" + self.serial)
            if command == "reverse":
                operation = (
                    "killforward:" + args[1]
                    if args[0] == "--remove"
                    else ("forward:norebind:" + args[0] + ";" + args[1])
                )
                connection.request("reverse:" + operation)
                _read_status(connection)
                return 0
            if command == "push":
                return self._push(connection)
            # 同一手机可能同时通过 USB 和网络连接；官方启动清理只能删除本次上传的文件。
            server_args = ["CLASSPATH=" + self.remote_server, *args[1:]]
            return self._shell(connection, server_args, stdout, stderr, unbounded=True)
        finally:
            connection.close()

    def _check_forward_owner(self, endpoint: str) -> None:
        """删除前核对当前映射，拒绝误删同端口上的其他会话；ADB 不提供原子比较删除。"""
        connection = Connection(self.timeout, self.cancelled)
        try:
            connection.request("host:list-forward")
            expected = [self.serial.encode(), endpoint.encode(), self.socket_name.encode()]
            entries = connection.read_string().splitlines()
            if not any(entry.split() == expected for entry in entries):
                raise AdbError("Forward endpoint is not owned by this scrcpy session.")
        finally:
            connection.close()

    def _push(self, connection: Connection) -> int:
        """每次上传固定文件；只有 SEND 完整确认才成功，失败不缓存或重放。"""
        with self.server_path.open("rb") as server:
            metadata = os.fstat(server.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Configured scrcpy server is not a regular file.")
            connection.request("sync:")
            target = (self.remote_server + ",33188").encode("ascii")
            connection.send(struct.pack("<4sI", b"SEND", len(target)) + target)
            while data := server.read(65536):
                connection.send(struct.pack("<4sI", b"DATA", len(data)) + data)
            connection.send(struct.pack("<4sI", b"DONE", int(metadata.st_mtime) & 0xFFFFFFFF))
            status, size = struct.unpack("<4sI", connection.read(8))
            if status == b"FAIL":
                if size <= 65536:
                    connection.read(size)
                raise AdbError("ADB rejected the scrcpy server transfer.")
            if status != b"OKAY":
                raise AdbError("Invalid ADB sync response.")
            return 0

    def cleanup_server(self) -> None:
        """只供会话所有者删除本次私有 JAR；固定路径、总时限、非零退出均保留失败。"""
        connection = Connection(self.timeout, self.cancelled)
        try:
            connection.request("host:transport:" + self.serial)
            code = self._shell(
                connection, ["rm", "-f", self.remote_server], io.BytesIO(), io.BytesIO(),
                unbounded=False,
            )
            if code:
                raise AdbError("Unable to remove the private scrcpy server.")
        finally:
            connection.close()

    def _shell(
        self,
        connection: Connection,
        args: list[str],
        stdout: BinaryIO,
        stderr: BinaryIO,
        *,
        unbounded: bool,
    ) -> int:
        """双流逐帧转发；退出帧前断流是失败，取消关闭连接且不另发远端 kill。"""
        connection.request("shell,v2,raw:" + " ".join(args))
        connection.send(struct.pack("<BI", 4, 0))
        # 仅完成握手后的读取解除短命令总时限，并保留 100ms 取消检查。
        if unbounded:
            connection.deadline = math.inf
        connection.cancelled = self.cancelled or (lambda: False)
        while True:
            channel, size = struct.unpack("<BI", connection.read(5))
            if channel not in (1, 2, 3) or size > 1024 * 1024:
                raise AdbError("Invalid scrcpy shell v2 frame.")
            if channel == 3 and size != 1:
                raise AdbError("Invalid scrcpy shell exit status.")
            data = connection.read(size)
            if channel == 3:
                return data[0]
            _write(stdout if channel == 1 else stderr, data)
