"""编码器查询的进程归属：回收 scrcpy 派生客户端，保留独立 ADB 服务。"""

import os
import subprocess
import time
import uuid

import psutil

from core.native_process import NativeCommandScope

ENCODER_SCOPE_ENV = "ADBLAB_SCRCPY_ENCODER_SCOPE"


def _executable_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


class ScrcpyEncoderScope(NativeCommandScope):
    """父进程和已登记 ADB 子客户端全部退出才交还查询资源。"""

    def __init__(self, scrcpy: str, adb: str) -> None:
        super().__init__()
        self._scrcpy = _executable_key(scrcpy)
        self._adb = _executable_key(adb)
        self._clients: set[psutil.Process] = set()
        self.token = uuid.uuid4().hex
        self._needs_discovery = False

    def _attach_process(self, token: object, process: subprocess.Popen) -> None:
        super()._attach_process(token, process)
        self._needs_discovery = True

    def _discover_orphaned_clients(self, deadline: float) -> None:
        """父提前退出时按继承的独占标记恢复归属，不凭名称或 PID 终止其他客户端。"""
        self._needs_discovery = True
        for candidate in psutil.process_iter(["exe"]):
            if time.monotonic() >= deadline:
                raise OSError("编码器查询的资源归属确认超时。")
            executable = candidate.info["exe"]
            if executable is None or _executable_key(executable) != self._adb:
                continue
            try:
                if candidate.environ().get(ENCODER_SCOPE_ENV) != self.token:
                    continue
                arguments = candidate.cmdline()
                if "fork-server" in arguments and "server" in arguments:
                    continue
                self._clients.add(candidate)
            except psutil.NoSuchProcess:
                continue
        self._needs_discovery = False

    def _resources_released(self, process: subprocess.Popen) -> bool:
        # psutil 保留创建时间身份，不能仅凭 PID 对复用后的进程执行清理。
        self._clients = {client for client in self._clients if client.is_running()}
        return (
            not self._needs_discovery and not self._clients
            and super()._resources_released(process)
        )

    def _cleanup_process(
        self, process: subprocess.Popen, *, completed: bool, timeout: float,
    ) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        suspended: list[psutil.Process] = []
        try:
            if process.poll() is None:
                root = psutil.Process(process.pid)
                root.suspend()
                suspended.append(root)
                # 冻结模式的根是隔离入口；先暂停其 scrcpy 子进程再枚举，关闭新客户端创建窗口。
                for child in root.children():
                    try:
                        if _executable_key(child.exe()) == self._scrcpy:
                            child.suspend()
                            suspended.append(child)
                    except psutil.NoSuchProcess:
                        continue
                for child in root.children(recursive=True):
                    try:
                        if _executable_key(child.exe()) != self._adb:
                            continue
                        arguments = child.cmdline()
                        if "fork-server" in arguments and "server" in arguments:
                            continue
                        self._clients.add(child)
                    except psutil.NoSuchProcess:
                        continue
                self._needs_discovery = False
            else:
                self._discover_orphaned_clients(deadline)
            for client in self._clients:
                try:
                    client.kill()
                except psutil.NoSuchProcess:
                    continue
            _gone, alive = psutil.wait_procs(
                list(self._clients), timeout=max(0.0, deadline - time.monotonic()),
            )
            if alive:
                raise OSError("编码器查询的 ADB 客户端尚未确认退出。")
        except psutil.NoSuchProcess:
            # 首次枚举前父退出时仍按标记恢复归属；不能把未知状态当作资源归零。
            raise OSError("编码器查询的资源归属尚未确认。") from None
        except psutil.Error as error:
            raise OSError("无法确认编码器查询的子进程归属。") from error
        finally:
            for paused in reversed(suspended):
                try:
                    paused.resume()
                except psutil.NoSuchProcess:
                    pass
        super()._cleanup_process(
            process, completed=completed, timeout=max(0.0, deadline - time.monotonic()),
        )
