"""原生工具启动和有界收尾；冻结 Windows 程序不改变 GUI 的 DLL 搜索状态。"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import uuid
import weakref
from typing import Any


def _should_isolate(isolate: bool, shell: bool) -> bool:
    return isolate and not shell and sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _launcher_prefix() -> list[str]:
    return [sys.executable, "--adblab-native-launch"]


class _CancellationEvent:
    """每次启动独占取消事件；保持到入口退出，避免尚未打开事件时丢失控制通道。"""

    def __init__(self):
        from ctypes import wintypes

        self._lock = threading.Lock()
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._api.CreateEventW.argtypes = [
            ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
        ]
        self._api.CreateEventW.restype = wintypes.HANDLE
        self._api.SetEvent.argtypes = [wintypes.HANDLE]
        self._api.SetEvent.restype = wintypes.BOOL
        self._api.CloseHandle.argtypes = [wintypes.HANDLE]
        self._api.CloseHandle.restype = wintypes.BOOL
        self.name = "Local\\ADBLabNative-" + uuid.uuid4().hex
        self._handle = self._api.CreateEventW(None, True, False, self.name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._finalizer = weakref.finalize(self, self._api.CloseHandle, self._handle)

    def signal(self) -> None:
        """取消只关闭当前工具的准入和客户端，不停止独立 ADB 服务。"""
        with self._lock:
            if self._finalizer.alive and not self._api.SetEvent(self._handle):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        with self._lock:
            self._finalizer()


class NativeProcess(subprocess.Popen):
    """Popen 兼容句柄；入口完成自有客户端清理后才发布退出码。"""

    def __init__(self, command: list[str], **kwargs: Any):
        self._cancellation = _CancellationEvent()
        launcher = [
            *_launcher_prefix(), "--cancel-event", self._cancellation.name,
            "--owner", str(os.getpid()), "--", *command,
        ]
        try:
            super().__init__(launcher, **kwargs)
        except BaseException:
            self._cancellation.close()
            raise

    def poll(self):
        code = super().poll()
        if code is not None:
            self._cancellation.close()
        return code

    def wait(self, timeout=None):
        code = super().wait(timeout=timeout)
        self._cancellation.close()
        return code

    def terminate(self) -> None:
        """请求入口终止已创建客户端；创建前收到取消时禁止启动工具。"""
        if self.poll() is None:
            self._cancellation.signal()

    def kill(self) -> None:
        """先合作取消，再有界回收无响应入口；不能把请求已发送当作已停止。"""
        if not self.stop(2.0):
            raise TimeoutError("原生工具清理超时，尚未确认客户端退出。")

    def stop(self, timeout: float) -> bool:
        """共享调用方清理预算；未确认退出时保留句柄，不能报告成功。"""
        deadline = time.monotonic() + max(0.0, timeout)
        self.terminate()
        try:
            self.wait(timeout=min(0.5, max(0.0, timeout) / 2))
        except subprocess.TimeoutExpired:
            return self._force_stop(deadline)
        return True

    def _force_stop(self, deadline: float) -> bool:
        """先暂停入口关闭创建窗口，仅回收直系客户端，保留其独立服务后代。"""
        import psutil

        if self.poll() is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        helper = None
        suspended = False
        try:
            helper = psutil.Process(self.pid)
            helper.suspend()
            suspended = True
            children = helper.children(recursive=False)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    continue
            _gone, alive = psutil.wait_procs(
                children, timeout=max(0.0, deadline - time.monotonic()),
            )
            if alive or time.monotonic() >= deadline:
                return False
            super().kill()
            self.wait(timeout=max(0.0, deadline - time.monotonic()))
            return True
        except (psutil.Error, OSError, subprocess.TimeoutExpired):
            return self.poll() is not None
        finally:
            if suspended and helper is not None and self.poll() is None:
                # 预算不足时允许入口继续响应已设置的取消，保留上层跟踪，不遗留暂停进程。
                try:
                    helper.resume()
                except psutil.NoSuchProcess:
                    self.poll()

    def cancel_and_drain(self, timeout: float = 2.0):
        """客户端回收与管道排空共用清理预算；独立服务持有写端不能拖住调用者。"""
        return cancel_and_drain_native(self, timeout=timeout)

    def __exit__(self, exc_type, value, traceback):
        try:
            if self.poll() is None and not self.stop(2.0):
                raise TimeoutError("原生工具清理超时，尚未确认客户端退出。")
        finally:
            close_native_pipes(self)


def close_native_pipes(process: subprocess.Popen) -> None:
    """关闭调用者拥有的管道；Windows 活跃 reader 保留流并在 EOF 时自行关闭。

    communicate 的读取线程正在 ReadFile 时持有流锁，同步 close 会绕过清理预算。
    独立后代仍持有写端时只转交读取端所有权，不能为取得 EOF 终止独立 ADB 服务。
    """
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, stream_name, None)
        reader = getattr(process, stream_name + "_thread", None)
        if stream is not None and (reader is None or not reader.is_alive()):
            stream.close()


def cancel_and_drain_native(process: subprocess.Popen, *, timeout: float):
    """仅终止自有客户端，在共享预算内确认退出并排空，不等待后代的管道 EOF。"""
    deadline = time.monotonic() + max(0.0, timeout)
    if isinstance(process, NativeProcess):
        if not process.stop(timeout):
            raise TimeoutError("原生工具清理超时，尚未确认客户端退出。")
    elif process.poll() is None:
        process.kill()
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            # 未确认客户端退出属于清理失败，不能伪装成原业务超时或抛到后台探测线程。
            raise TimeoutError("原生工具清理超时，尚未确认客户端退出。") from error
    try:
        return process.communicate(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        # reader 的最终收口依赖独立后代关闭写端；调用者只发布超时/取消，不伪造成功输出。
        return error.output, error.stderr


def stop_native_process(process: subprocess.Popen, *, timeout: float) -> bool | None:
    """隔离入口走合作取消；普通进程返回 None，继续原有树清理规则。"""
    if not isinstance(process, NativeProcess):
        return None
    return process.stop(timeout)


def popen_native(command: list[str], *, isolate: bool = False, **kwargs: Any) -> subprocess.Popen:
    """仅在显式原生工具边界隔离；本应用 worker、源码及其他平台保持原启动方式。"""
    if not _should_isolate(isolate, bool(kwargs.get("shell", False))):
        return subprocess.Popen(command, **kwargs)
    if not command or not os.path.isabs(command[0]) or not os.path.isfile(command[0]):
        raise FileNotFoundError("原生工具不可用，请重新选择有效的可执行文件。")
    return NativeProcess(command, **kwargs)


def run_native(
    command: list[str], *, isolate: bool = False, input=None, capture_output: bool = False,
    timeout: float | None = None, check: bool = False, **kwargs: Any,
) -> subprocess.CompletedProcess:
    """保留 run 的流和退出契约；隔离入口超时后先确认客户端回收再返回失败。"""
    if not _should_isolate(isolate, bool(kwargs.get("shell", False))):
        return subprocess.run(
            command, input=input, capture_output=capture_output,
            timeout=timeout, check=check, **kwargs,
        )
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output")
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    with popen_native(command, isolate=True, **kwargs) as process:
        assert isinstance(process, NativeProcess)
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = process.cancel_and_drain()
            error.output, error.stderr = stdout, stderr
            error.cmd = command
            raise
        except BaseException:
            process.cancel_and_drain()
            raise
        returncode = process.wait()
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)
