"""原生工具启动和有界收尾；隔离冻结程序对外部工具的动态库搜索影响。"""

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


def native_tool_environment(environment: dict[str, str]) -> dict[str, str]:
    """复制 Linux 原生工具环境，恢复冻结启动前的库路径，不修改调用方环境。"""
    cleaned = dict(environment)
    original = cleaned.get("LD_LIBRARY_PATH_ORIG")
    if original is None:
        cleaned.pop("LD_LIBRARY_PATH", None)
    else:
        cleaned["LD_LIBRARY_PATH"] = original
    return cleaned


def _launcher_prefix() -> list[str]:
    return [sys.executable, "--adblab-native-launch"]


class NativeCommandScope:
    """串行原生命令的资源归属；启动中和未确认退出的客户端都阻止下一次准入。

    停止信号永久关闭本作用域，只由命令线程终止、排空正在使用的进程。后台 wait
    仅在该线程交还残留句柄后接管有界清理，不与 communicate 争用同一进程。
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._stopped = threading.Event()
        self._token: object | None = None
        self._process: subprocess.Popen | None = None
        self._owned = False

    def request_stop(self) -> None:
        """幂等设置停止信号，不在调用线程等待或操作子进程。"""
        self._stopped.set()
        with self._condition:
            self._condition.notify_all()

    def _stop_requested(self) -> bool:
        return self._stopped.is_set()

    def _begin_command(self) -> object | None:
        """在 popen 前登记启动义务；停止后拒绝准入，旧资源未退出时报告失败。"""
        with self._condition:
            self._release_exited()
            if self._token is not None:
                raise OSError("上一条原生命令尚未确认退出。")
            if self._stopped.is_set():
                return None
            self._token = object()
            self._owned = True
            return self._token

    def _attach_process(self, token: object, process: subprocess.Popen) -> None:
        """接管已登记启动返回的句柄；即使停止已发生，也必须先保留资源归属。"""
        with self._condition:
            if self._token is not token:
                raise RuntimeError("原生命令启动登记已失效。")
            self._process = process

    def _finish_command(self, token: object) -> None:
        """执行方结束管道收尾后交还句柄；仅确认退出才解除登记。"""
        with self._condition:
            if self._token is token:
                self._owned = False
                self._release_exited()
                self._condition.notify_all()

    def _release_exited(self) -> None:
        """持锁检查已交还的资源；poll 异常表示无法确认退出，必须保留残留。"""
        if self._owned or self._token is None:
            return
        if self._process is not None:
            try:
                if self._process.poll() is None:
                    return
            except Exception:
                return
        self._process = None
        self._token = None

    def is_running(self) -> bool:
        """启动中、执行方尚未交还或客户端退出状态未知时均保守报告运行中。"""
        with self._condition:
            self._release_exited()
            return self._token is not None

    def wait(self, timeout: float) -> bool:
        """后台有界等待；停止后可接管残留客户端，失败仍持有句柄供监督器报告。"""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._condition:
                self._release_exited()
                if self._token is None:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                process = self._process
                if self._owned or process is None or not self._stopped.is_set():
                    self._condition.wait(min(0.05, remaining))
                    continue
                # 同一时刻仅一个后台等待者能接管，其他等待者不触碰该进程。
                self._owned = True
            try:
                if isinstance(process, NativeProcess):
                    process.stop(remaining)
                elif process.poll() is None:
                    process.kill()
                    process.wait(timeout=max(0.0, deadline - time.monotonic()))
                close_native_pipes(process)
            except Exception:
                # 清理失败通过仍为 running/返回 False 暴露，不能误报已停止或丢弃句柄。
                return False
            finally:
                with self._condition:
                    self._owned = False
                    self._release_exited()
                    self._condition.notify_all()
                    if self._token is not None:
                        self._condition.wait(min(0.05, max(0.0, deadline - time.monotonic())))


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
    """隔离显式原生工具的库搜索；应用 worker 保留自身冻结运行环境。"""
    shell = bool(kwargs.get("shell", False))
    if isolate and not shell and sys.platform == "linux" and getattr(sys, "frozen", False):
        environment = kwargs.get("env")
        kwargs["env"] = native_tool_environment(
            dict(os.environ) if environment is None else environment,
        )
    if not _should_isolate(isolate, shell):
        return subprocess.Popen(command, **kwargs)
    if not command or not os.path.isabs(command[0]) or not os.path.isfile(command[0]):
        raise FileNotFoundError("原生工具不可用，请重新选择有效的可执行文件。")
    return NativeProcess(command, **kwargs)


def run_native(
    command: list[str], *, isolate: bool = False, input=None, capture_output: bool = False,
    timeout: float | None = None, check: bool = False, **kwargs: Any,
) -> subprocess.CompletedProcess:
    """保留 run 的流和退出契约；各启动方式共用两秒的终止及排空预算。"""
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output")
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    process = popen_native(command, isolate=isolate, **kwargs)
    try:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = cancel_and_drain_native(process, timeout=2.0)
            # Windows 的 run 用最终 communicate 输出补全异常；排空仍超时则保留已捕获数据。
            # POSIX 原异常已携带 bytes，不能被 text 模式的排空结果替换。
            if sys.platform == "win32":
                if stdout is not None:
                    error.output = stdout
                if stderr is not None:
                    error.stderr = stderr
            error.cmd = command
            raise
        except BaseException:
            cancel_and_drain_native(process, timeout=2.0)
            raise
        returncode = process.wait()
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
    finally:
        # 普通 Popen 上下文退出会同步关闭活跃 reader 的流，绕过上面的共享预算。
        close_native_pipes(process)
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)
