"""通过既有执行边界轮询设备，并随 Qt 载荷保留发现代次。"""

import subprocess
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from core.adb_runtime import local_server_environment
from core.adb_transport import CommandCancelled, acquire_adb_client
from core.exec import CommandRunner, ProcessRunner, adb_client_lock, adb_runtime
from core.native_process import cancel_and_drain_native, close_native_pipes


class _ScannedDevices(list[str]):
    """随列表保留捕获代次，Qt 排队和界面防抖都不能把旧结果变成新快照。"""

    def __init__(self, devices: list[str], token: tuple[int, int] | None):
        super().__init__(devices)
        self.discovery_token = token


class _ScanDiscoveryState(str):
    """失败状态与设备列表使用同一代次，晚到错误也不能回退已恢复的界面。"""

    discovery_token: tuple[int, int] | None

    def __new__(cls, state: str, token: tuple[int, int] | None):
        value = super().__new__(cls, state)
        value.discovery_token = token
        return value


class _ScanThread(QThread):
    """以低频率轮询 ``adb devices`` 的长生命周期线程。

    原生扫描由 ProcessRunner 跟踪，以最多 100ms 的分片读取输出；客户端已退出
    但后代仍持有管道时也能响应停止和截止时间。清理只终止自有客户端，
    未确认退出的进程仍由全局关闭屏障跟踪。
    """

    SCAN_CALL_TIMEOUT_S = 15.0

    devices_changed = Signal(object)
    discovery_state_changed = Signal(object)

    def __init__(self, parent=None, interval_ms: int = 15000):
        super().__init__(parent)
        self._stop_flag = False
        self._interval_ms = max(3000, int(interval_ms))
        self._snapshot_invalidated = threading.Event()
        self.discovery_token: Callable[[], tuple[int, int] | None] = lambda: None

    def stop(self):
        """只设置协作停止标志，不等待线程退出。

        调用方必须通过 finished/wait 或关闭监督器确认资源结束。
        """
        self._stop_flag = True

    def invalidate_snapshot(self) -> None:
        """让下一次成功轮询重发快照，用于恢复外部刷新失败状态。"""

        self._snapshot_invalidated.set()

    def run(self):
        from models.adb_device import parse_connected_devices

        runner: ProcessRunner | None = None
        last_devices = None  # 首次轮询必须发布设备列表。
        last_token = None
        last_state = "scanning"
        while not self._stop_flag:
            # 回调抛错时 except 仍需要对比上一轮代次；不能依赖本轮 try 内首次赋值。
            token = last_token
            runtime = adb_runtime()
            if runtime is not None:
                # 恢复检查独立于原生扫描成功和普通命令忙碌状态，避免慢客户端拖住恢复。
                runtime.request_device_check()
            fast_scan = runtime is not None and runtime.can_scan_fast()
            if not fast_scan and CommandRunner.active_count() != 0:
                # 有受管命令在执行时跳过本轮，等待完整间隔后再试。
                if self._sleep_interruptibly(self._interval_ms):
                    return
                continue
            try:
                token = self.discovery_token()
                deadline = time.monotonic() + self.SCAN_CALL_TIMEOUT_S
                admission = (
                    runtime.wait_for_device_check(
                        self.SCAN_CALL_TIMEOUT_S, lambda: self._stop_flag,
                    )
                    if runtime is not None else None
                )
                if admission is not None and admission.kind == "cancelled":
                    return
                # 等待期间能力和用户选择都可能改变，重新选择并继续消耗同一轮预算。
                fast_scan = runtime is not None and runtime.can_scan_fast()
                remaining = deadline - time.monotonic()
                if admission is not None or remaining <= 0:
                    output = None
                elif fast_scan:
                    result = CommandRunner.run(
                        ["adb", "devices", "-l"], timeout=remaining,
                        cancelled=lambda: self._stop_flag,
                    )
                    if result.stale:
                        # 晚到列表不代表发现失败，保持当前快照并等待下一轮正常扫描。
                        if self._sleep_interruptibly(self._interval_ms):
                            return
                        continue
                    output = result.output if result.success else None
                else:
                    if runner is None:
                        runner = ProcessRunner()
                    try:
                        acquire_adb_client(deadline, lambda: self._stop_flag)
                    except (CommandCancelled, TimeoutError):
                        output = None
                    else:
                        try:
                            output = self._run_devices_scan(runner, deadline=deadline)
                        finally:
                            adb_client_lock.release()
                if self._stop_flag:
                    return
                if output is None:
                    if last_state != "unavailable" or token != last_token:
                        self.discovery_state_changed.emit(_ScanDiscoveryState("unavailable", token))
                    last_state = "unavailable"
                else:
                    devices = parse_connected_devices(output)
                    device_set = tuple(sorted(devices))
                    # 成功状态由同一设备快照在主线程提交，避免 ready/empty
                    # 先于 300ms 防抖列表到达。故障恢复时即使集合相同也重发。
                    if (
                        device_set != last_devices
                        or last_state == "unavailable"
                        or self._snapshot_invalidated.is_set()
                        or token != last_token
                    ):
                        self._snapshot_invalidated.clear()
                        last_devices = device_set
                        self.devices_changed.emit(_ScannedDevices(devices, token))
                    last_state = "ready" if devices else "empty"
                last_token = token
            except Exception:
                if not self._stop_flag and (last_state != "unavailable" or token != last_token):
                    self.discovery_state_changed.emit(_ScanDiscoveryState("unavailable", token))
                last_state = "unavailable"
                last_token = token
            if self._sleep_interruptibly(self._interval_ms):
                return

    def _run_devices_scan(
        self, runner: ProcessRunner, *, deadline: float | None = None,
    ) -> str | None:
        """执行一次 ``adb devices`` 并返回 stdout 文本。

        发现准入与原生客户端共享截止时间；独立调用时仍使用原有扫描预算。
        失败、取消和超时返回 None，另用最多 0.5 秒确认客户端退出及排空管道；
        独立 ADB 服务仍持有写端时不等待 EOF，也不终止共享服务。
        """
        if deadline is None:
            deadline = time.monotonic() + self.SCAN_CALL_TIMEOUT_S
        if self._stop_flag or time.monotonic() >= deadline:
            return None
        try:
            proc = runner.start(
                "device_scan",
                ["adb", "devices"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return None
        completed = False
        try:
            try:
                while not self._stop_flag:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    try:
                        # 持续排空两个管道，避免大量设备或诊断输出反向阻塞客户端。
                        stdout, stderr = proc.communicate(timeout=min(0.1, remaining))
                    except subprocess.TimeoutExpired:
                        continue
                    completed = True
                    if proc.returncode == 0:
                        return stdout
                    if (stderr and "failed to check server version" in stderr
                            and local_server_environment() and not self._stop_flag):
                        from core.adb_transport import capture

                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return None
                        listed = capture(
                            "devices", [], serial=None,
                            timeout=remaining, cancelled=lambda: self._stop_flag,
                        )
                        if listed.kind == "completed" and listed.returncode == 0:
                            return listed.stdout.decode("utf-8", errors="ignore")
                    return None
                return None
            finally:
                try:
                    if not completed:
                        cancel_and_drain_native(proc, timeout=0.5)
                finally:
                    try:
                        close_native_pipes(proc)
                    finally:
                        # 清理失败时保留实例和全局登记，交给应用关闭屏障继续处理。
                        runner.release_finished("device_scan", proc)
        except Exception:
            return None

    def _sleep_interruptibly(self, delay_ms: int) -> bool:
        """把等待拆成 100ms 小段，返回是否收到停止请求。"""

        remaining = max(0, int(delay_ms))
        while remaining > 0:
            if self._stop_flag:
                return True
            wait_ms = min(100, remaining)
            self.msleep(wait_ms)
            remaining -= wait_ms
        return bool(self._stop_flag)
