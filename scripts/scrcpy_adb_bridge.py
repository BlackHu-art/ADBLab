"""scrcpy 4.1 私有 ADB CLI；无需 Qt，仅连接已有本机服务并随父进程退出。"""

from __future__ import annotations

import io
import os
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.adb_transport import AdbError, CancelCheck, CommandCancelled
from core.scrcpy_adb_protocol import ScrcpyAdbProtocol, host_version
from core.scrcpy_session import (
    helper_lease,
    mark_server_pending,
    session_configuration,
    session_scid,
    session_token,
)


def _local_environment(environment: Mapping[str, str]) -> None:
    allowed = {
        "ADB_SERVER_SOCKET": {"", "tcp:localhost:5037", "tcp:127.0.0.1:5037", "tcp:5037"},
        "ANDROID_ADB_SERVER_ADDRESS": {"", "localhost", "127.0.0.1"},
        "ANDROID_ADB_SERVER_PORT": {"", "5037"},
    }
    if any(environment.get(key, "") not in values for key, values in allowed.items()):
        raise ValueError("Only the existing local ADB server on port 5037 is supported.")


class _ProcessWatch:
    """Windows 持有原进程句柄防 PID 复用；其他平台只检查既有进程，不发送终止信号。"""

    def __init__(self, pid: int):
        if pid <= 1:
            raise ValueError("A live scrcpy parent process is required.")
        self.pid = pid
        self.api: Any = None
        self.handle: Any = None
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.api.OpenProcess.restype = wintypes.HANDLE
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.WaitForSingleObject.restype = wintypes.DWORD
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.api.CloseHandle.restype = wintypes.BOOL
            self.handle = self.api.OpenProcess(0x00100000, False, pid)
            if not self.handle:
                raise ValueError("Scrcpy parent or owner process is unavailable.")

    def alive(self) -> bool:
        """只读观察存活状态；未知 Windows 等待结果也停止业务准入。"""
        if self.api is not None:
            return self.api.WaitForSingleObject(self.handle, 0) == 258
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def close(self) -> None:
        """释放本地观察句柄，不影响所观察进程。"""
        if self.api is not None and self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def helper_lifetime(environment: Mapping[str, str]) -> Iterator[CancelCheck]:
    """CLI 资源归属入口；全部命令检查 scrcpy 直接父进程和 ADBLab owner 的存活。"""
    owner = int(environment["ADBLAB_SCRCPY_OWNER_PID"])
    parent = os.getppid()
    watches: list[_ProcessWatch] = []
    try:
        for pid in {owner, parent}:
            watches.append(_ProcessWatch(pid))

        def cancelled() -> bool:
            # POSIX 的重新托管可在 PID 再利用之前表明原直接父进程已经消失。
            return os.getppid() != parent or any(not watch.alive() for watch in watches)

        with helper_lease(Path(environment["ADBLAB_SCRCPY_SESSION_FILE"])):
            if cancelled():
                raise CommandCancelled
            yield cancelled
    finally:
        for watch in watches:
            watch.close()


def _watchdog(cancelled: CancelCheck, stopped: threading.Event) -> None:
    """父进程丢失后给正常取消留出收口时间；堵塞的输出或系统调用由进程退出兜底。"""
    while not stopped.wait(0.1):
        if cancelled():
            if not stopped.wait(1.0):
                # 只终止当前专用 helper，操作系统会关闭其套接字、管道和租约。
                os._exit(130)
            return


def main(argv: list[str] | None = None) -> int:
    """补齐父进程主动关闭的标准流；有效管道保持原对象，诊断不会转入数据 stdout。"""
    with ExitStack() as streams:
        for stream, redirect in ((sys.stdout, redirect_stdout), (sys.stderr, redirect_stderr)):
            if _unavailable_standard_stream(stream):
                sink = streams.enter_context(open(os.devnull, "w", encoding="utf-8"))
                streams.enter_context(redirect(sink))
        return _main(argv)


def _unavailable_standard_stream(stream: Any) -> bool:
    if stream is None or stream.closed:
        return True
    try:
        os.fstat(stream.fileno())
    except io.UnsupportedOperation:
        # 测试捕获流与内存流没有文件描述符，仍拥有可用的写入接口。
        return False
    except (OSError, ValueError):
        return True
    return False


def _main(argv: list[str] | None = None) -> int:
    """兼容 scrcpy 的有限原生 argv；失败不启动原生 ADB、不重放、不泄露参数诊断。"""
    args = list(sys.argv[1:] if argv is None else argv)
    environment = dict(os.environ)
    try:
        if args == ["--self-check"]:
            sys.stdout.buffer.write(b"scrcpy-adb-bridge: ready\n")
            sys.stdout.buffer.flush()
            return 0
        _local_environment(environment)
        if args == ["--probe-server"]:
            host_version(timeout=3.0)
            return 0
        serial, server, _, ports, session_file = session_configuration(environment)
        selected = None
        if args[:1] == ["-s"] and len(args) >= 3:
            selected, args = args[1], args[2:]
        if not args or (selected is not None and selected != serial):
            raise ValueError("Command target does not match this scrcpy launch.")
        command, command_args = args[0], args[1:]
        if command not in {"start-server", "devices"} and selected != serial:
            raise ValueError("An explicit scrcpy device selector is required.")
        with helper_lifetime(environment) as cancelled:
            if cancelled():
                raise CommandCancelled
            scid = session_scid(environment, command, command_args)
            protocol = ScrcpyAdbProtocol(
                serial,
                server,
                scid=scid,
                port_range=ports,
                session_token=session_token(session_file),
                cancelled=cancelled,
            )
            protocol.validate(command, command_args)
            if command == "push":
                mark_server_pending(environment)
            stopped = threading.Event()
            watcher = threading.Thread(target=_watchdog, args=(cancelled, stopped), daemon=True)
            watcher.start()
            try:
                return protocol.execute(
                    command,
                    command_args,
                    stdout=sys.stdout.buffer,
                    stderr=sys.stderr.buffer,
                )
            finally:
                stopped.set()
                watcher.join()
    except ValueError as exc:
        print(f"scrcpy-adb-bridge: {exc}", file=sys.stderr)
        return 2
    except (CommandCancelled, KeyboardInterrupt):
        print("scrcpy-adb-bridge: cancelled; connection closed.", file=sys.stderr)
        return 130
    except TimeoutError:
        print(
            "scrcpy-adb-bridge: handshake or transfer timed out; request was not retried.",
            file=sys.stderr,
        )
        return 124
    except ConnectionRefusedError:
        print("scrcpy-adb-bridge: local ADB server unavailable.", file=sys.stderr)
        return 1
    except AdbError as exc:
        print(f"scrcpy-adb-bridge: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("scrcpy-adb-bridge: I/O failed; request was not retried.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
