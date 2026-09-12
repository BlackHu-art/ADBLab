"""应用级 ADB 能力和性能选择；导入无 I/O，业务请求不参与竞速或重放。"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO

from core.adb_transport import CancelCheck, ExecutionResult, capture
from utils import adb_debug


def native_capture(
    cmd: list[str],
    timeout: float,
    cancelled: CancelCheck,
    *,
    stdout_sink: BinaryIO | None = None,
) -> ExecutionResult:
    """执行可取消的原生探针或短命令；只终止本次创建的客户端，不停止 ADB 服务。"""
    deadline = time.monotonic() + timeout
    if cancelled():
        return ExecutionResult(kind="cancelled")
    adb_debug.command(cmd, backend="native_client", timeout=timeout)
    try:
        with subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=stdout_sink if stdout_sink is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as proc:
            try:
                while True:
                    if cancelled():
                        adb_debug.command(
                            cmd, backend="native_client", phase="finish", status="cancelled",
                        )
                        return ExecutionResult(kind="cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        adb_debug.command(
                            cmd, backend="native_client", phase="finish", status="timeout",
                        )
                        return ExecutionResult(kind="timeout")
                    try:
                        out, err = proc.communicate(timeout=min(0.1, remaining))
                        if adb_debug.enabled():
                            adb_debug.command(
                                cmd, backend="native_client", phase="finish", status="completed",
                                returncode=proc.returncode,
                            )
                        return ExecutionResult(out or b"", err, proc.returncode)
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
    except OSError as exc:
        adb_debug.command(
            cmd, backend="native_client", phase="finish", status="transport",
            error_type=type(exc).__name__, errno=exc.errno, winerror=getattr(exc, "winerror", None),
        )
        return ExecutionResult(stderr=b"ADB process failed", kind="transport")


@dataclass(frozen=True)
class RuntimeSnapshot:
    """供界面消费的脱敏状态；设备标识和协议参数不进入展示快照。"""

    checking: bool
    available: bool
    native_only: bool
    fast_devices: bool
    fast_shell_devices: int
    checked_devices: int
    selection_mode: str = "auto"
    status: str = "idle"

    @property
    def effective_native_only(self) -> bool:
        """反映实际可选后端，不能用来替代用户模式或禁止后续自动恢复。"""
        return not (self.fast_devices or self.fast_shell_devices)


@dataclass
class _BackendState:
    """把当前可用性与本次连接的测速偏好分开，短暂故障不丢失有效基准。"""

    available: bool = False
    preference: bool | None = None
    checked: bool = False
    next_check: float = 0.0
    epoch: int = 0
    benchmarked: bool = False

    @property
    def fast(self) -> bool:
        """返回自动模式的能力与测速判断；最终选择还须应用用户模式。"""
        return self.available and self.preference is not False


def local_server_environment() -> bool:
    """仅适配默认本地服务；显式服务环境由原生 ADB 解释，避免误选端点。"""
    return not any(
        os.environ.get(key)
        for key in (
            "ADB_SERVER_SOCKET",
            "ANDROID_ADB_SERVER_ADDRESS",
            "ANDROID_ADB_SERVER_PORT",
        )
    )


class AdbRuntime:
    """管理一次应用运行的探测、策略和活动请求，关闭分为停止探测和最终封闭两阶段。"""

    PROBE_TIMEOUT = 2.0
    SOCKET_TIMEOUT = 1.0
    CAPABILITY_BUDGET = 3.0
    BOOTSTRAP_TIMEOUT = 30.0
    CHECK_INTERVAL = 10.0
    PROBE_COMMAND = "printf ADBLAB_OUT; printf ADBLAB_ERR >&2; exit 7"

    def __init__(
        self,
        resolver: Callable[[], str | None],
        *,
        ready: Callable[[], None] = lambda: None,
        changed: Callable[[RuntimeSnapshot], None] = lambda _snapshot: None,
        diagnostic: Callable[[str], None] = lambda _message: None,
        probe_serial: str | None = None,
    ):
        self._resolver = resolver
        self._ready = ready
        self._changed = changed
        self._diagnostic = diagnostic
        # 隔离采集进程只验证自己的目标，避免多会话重复探测其他设备。
        self._probe_serial = probe_serial
        self._condition = threading.Condition(threading.RLock())
        self._thread: threading.Thread | None = None
        self._probe_stop = threading.Event()
        self._request_stop = threading.Event()
        self._closed = False
        self._draining = False
        self._checking = False
        self._native_only = False
        self._mode = "auto"
        self._status = "idle"
        self._host = _BackendState()
        self._shell: dict[str, _BackendState] = {}
        self._topology: dict[str, str] = {}
        self._generation = 0
        self._active = 0
        self._path: str | None = None
        self._ready_sent = False
        self._full_probe = True
        # 本地服务引导只在运行实例首次初始化的连接被明确拒绝时尝试一次。
        self._bootstrap_pending = True
        self._allow_bootstrap = False
        self._probe_checked: set[int] = set()

    def snapshot(self) -> RuntimeSnapshot:
        """原子读取当前能力状态，不暴露可变策略。"""
        with self._condition:
            usable = (
                not self._native_only and not self._closed and not self._draining
                and local_server_environment()
            )
            status = self._status
            if not local_server_environment():
                status = "custom_server"
            elif not self._checking and self._host.available and any(
                state.checked and not state.available for state in self._shell.values()
            ):
                status = "shell_unavailable"
            return RuntimeSnapshot(
                self._checking,
                self._host.available,
                self._native_only,
                self._selected(self._host) and usable,
                sum(self._selected(state) for state in self._shell.values())
                if usable and self._host.available else 0,
                sum(state.checked for state in self._shell.values()),
                self._mode,
                status,
            )

    @property
    def selection_mode(self) -> str:
        """返回用户选择，独立于暂时失效或自动测速形成的实际后端。"""
        with self._condition:
            return self._mode

    def _selected(self, state: _BackendState) -> bool:
        """持锁选择已验证能力；手动快速只覆盖测速偏好，不绕过能力和原生模式。"""
        return not self._native_only and state.available and (
            self._mode == "fast" or state.preference is not False
        )

    def _publish(self) -> None:
        if self._probe_stop.is_set():
            return
        self._changed(self.snapshot())

    def start(self, *, force: bool = True, reset_mode: bool = False) -> bool:
        """启动唯一探测任务；仅首次初始化可启动服务，强制重测不重启服务。"""
        with self._condition:
            if (
                self._closed
                or self._draining
                or self._checking
                or (self._native_only and not force)
            ):
                return False
            if reset_mode:
                self._mode = "auto"
                self._native_only = False
            self._checking = True
            self._status = "checking"
            self._probe_checked = set()
            self._full_probe = force
            self._allow_bootstrap = self._bootstrap_pending
            self._bootstrap_pending = False
            if force:
                # 旧业务结果不能覆盖用户显式重测所建立的新状态。
                self._host.epoch += 1
                for state in self._shell.values():
                    state.epoch += 1
            previous = self._thread
            self._thread = threading.Thread(
                target=self._probe, args=(previous,), name="adblab-adb-probe",
            )
            self._thread.start()
        return True

    def recheck(self) -> bool:
        """用户显式重测原子恢复自动选择；之后的手动选择仍优先于晚到测速。"""
        return self.start(force=True, reset_mode=True)

    def set_native_only(self, enabled: bool) -> None:
        """只改变后续调用的选择，不停止已发送请求，也不写入持久配置。"""
        self.set_mode("native" if enabled else "fast")

    def set_mode(self, mode: str) -> None:
        """实时切换后续请求；只在实际改选且缺少能力时唤起验证，不重放在途业务。"""
        if mode not in {"auto", "fast", "native"}:
            raise ValueError("Invalid ADB selection mode")
        report = None
        with self._condition:
            if self._closed or self._draining or mode == self._mode:
                return
            self._mode = mode
            self._native_only = mode == "native"
            self._condition.notify_all()
            if not self._native_only and local_server_environment() and (
                not self._host.available
                or any(not state.available for state in self._shell.values())
            ):
                self._host.next_check = 0
                for state in self._shell.values():
                    if not state.available:
                        state.next_check = 0
                self.start(force=False)
            if adb_debug.enabled():
                report = self.snapshot(), self._path
        if report is not None:
            snapshot, path = report
            adb_debug.event(
                "mode", selection_mode=snapshot.selection_mode, host_available=snapshot.available,
                selected_adb=path, fast_devices=snapshot.fast_devices,
                fast_shell_devices=snapshot.fast_shell_devices,
                checked_devices=snapshot.checked_devices, status=snapshot.status,
            )
        self._publish()

    def _service_ready(self) -> None:
        with self._condition:
            first = not self._ready_sent
            self._ready_sent = True
        if first and not self._probe_stop.is_set():
            self._ready()

    @staticmethod
    def _prefer_socket(
        native: ExecutionResult, elapsed: float, socket_elapsed: float,
    ) -> bool | None:
        # 超时仅能证明直连有收益，不能证明原生更快；无效基准不改写已有偏好。
        if native.kind == "timeout":
            return True if socket_elapsed < elapsed * 0.8 else None
        if native.kind != "completed":
            return None
        return socket_elapsed + 0.02 < elapsed * 0.8

    @staticmethod
    def _valid_listing(result: ExecutionResult) -> bool:
        """原生列表须真正成功；不同采样时刻的设备集合允许正常变化。"""
        return (
            result.kind == "completed" and result.returncode == 0
            and result.stdout.lstrip().startswith(b"List of devices attached")
        )

    def _current(self, state: _BackendState, epoch: int, serial: str | None = None) -> bool:
        """持锁验证结果归属；状态替换、失效和关闭均拒绝晚到结果。"""
        return (
            not self._closed
            and not self._draining
            and (self._host if serial is None else self._shell.get(serial)) is state
            and state.epoch == epoch
        )

    def _invalidate(self, state: _BackendState) -> None:
        """持锁撤销当前能力并保留测速偏好，不重放导致失效的业务命令。"""
        state.available = False
        state.epoch += 1
        state.next_check = time.monotonic() + self.CHECK_INTERVAL
        if state is self._host:
            for device in self._shell.values():
                device.available = False
                device.epoch += 1
                # 服务恢复后仍分别尊重各设备已有的检查时间。
                device.next_check = min(device.next_check, state.next_check)
        self._condition.notify_all()

    def note_server_restart(self) -> None:
        """外部重启 5037 服务后作废能力并立即重测，避免沿用已断开的连接状态。

        由「重启 ADB」入口在成功结果到达后调用；只影响后续命令，不重放在途请求。
        """

        with self._condition:
            if self._closed or self._draining:
                return
            self._invalidate(self._host)
            self._host.next_check = 0.0
            for state in self._shell.values():
                state.next_check = 0.0
        self.start(force=True)

    def _probe(self, previous: threading.Thread | None = None) -> None:
        """原子交接检查准入；新线程先 join 旧线程，保证探测工作从不并行。"""
        if previous is not None:
            previous.join()
        try:
            while True:
                self._probe_once()
                with self._condition:
                    if (
                        not self._draining and not self._native_only
                        and self._host.available and local_server_environment()
                        and any(
                            id(state) not in self._probe_checked and not state.available
                            and time.monotonic() >= state.next_check
                            for state in self._shell.values()
                        )
                    ):
                        # 收尾期间接到的新目标由当前线程继续处理，不依赖下一次扫描。
                        self._full_probe = False
                        continue
                    self._checking = False
                    if self._status in {"checking", "retrying", "starting_server"}:
                        self._status = "ready" if self._host.available else "idle"
                    self._condition.notify_all()
                    return
        finally:
            self._service_ready()
            report = None
            with self._condition:
                # 新一轮可能已取得准入并在 join 当前线程，旧收尾不能清除其 checking。
                if self._thread is threading.current_thread():
                    self._checking = False
                    if self._status in {"checking", "retrying", "starting_server"}:
                        self._status = "ready" if self._host.available else "idle"
                    self._condition.notify_all()
                    self._publish()
                    if (
                        adb_debug.enabled() and not self._closed and not self._draining
                        and not self._probe_stop.is_set()
                    ):
                        report = self.snapshot(), self._path
            if report is not None:
                snapshot, path = report
                adb_debug.event(
                    "probe_complete", selection_mode=snapshot.selection_mode,
                    selected_adb=path, host_available=snapshot.available,
                    fast_devices=snapshot.fast_devices,
                    fast_shell_devices=snapshot.fast_shell_devices,
                    checked_devices=snapshot.checked_devices, status=snapshot.status,
                )

    def _probe_once(self) -> None:
        try:
            self._publish()
            path = self._resolver()
            adb_debug.event(
                "probe_start", selected_adb=path, selection_mode=self.selection_mode,
                endpoint="127.0.0.1:5037" if local_server_environment() else "custom",
            )
            with self._condition:
                if self._draining:
                    return
                if path != self._path or not local_server_environment():
                    self._host = _BackendState()
                    self._shell.clear()
                    self._topology.clear()
                    self._generation += 1
                self._path = path
                self._condition.notify_all()
                host = self._host
                host_epoch = host.epoch
                # 未就绪服务需要完整连接窗口，避免延迟拒绝被拆分预算误判为超时。
                host_timeout = self.SOCKET_TIMEOUT if host.available else self.CAPABILITY_BUDGET
                generation = self._generation
                host.next_check = time.monotonic() + self.CHECK_INTERVAL
            if not path or not local_server_environment():
                with self._condition:
                    self._status = "missing_adb" if not path else "custom_server"
                self._diagnostic(f"ADB environment status={self._status}")
                adb_debug.event("probe_result", status=self._status)
                return
            stop = self._probe_stop.is_set
            # 已验证服务的健康检查刻意只保留一次 1 秒尝试：失败后按 CHECK_INTERVAL
            # 节流，在下一轮用完整能力预算恢复，避免把抖动放大成连续重试。
            listing, socket_elapsed = self._probe_capability(
                "devices", ["-l"], serial=None,
                retry=self._full_probe or not host.available,
                initial_timeout=host_timeout,
                current=lambda: self._current(host, host_epoch) and generation == self._generation,
            )
            if listing.kind == "unavailable" and self._allow_bootstrap and not stop():
                with self._condition:
                    if not self._current(host, host_epoch) or generation != self._generation:
                        return
                    self._status = "starting_server"
                self._diagnostic("ADB bootstrap status=starting_server")
                self._publish()
                started = time.monotonic()
                # 仅首次引导容纳原生客户端和服务冷启动，不延长扫描及业务命令预算。
                bootstrap = native_capture([path, "start-server"], self.BOOTSTRAP_TIMEOUT, stop)
                elapsed = time.monotonic() - started
                self._diagnostic(
                    f"ADB bootstrap result={bootstrap.kind} returncode={bootstrap.returncode} "
                    f"elapsed_ms={elapsed * 1000:.0f}"
                )
                listing, socket_elapsed = self._probe_capability(
                    "devices", ["-l"], serial=None, retry=True,
                    initial_timeout=host_timeout,
                    current=lambda: (
                        self._current(host, host_epoch) and generation == self._generation
                    ),
                )
            with self._condition:
                if not self._current(host, host_epoch) or generation != self._generation:
                    return
                host.checked = True
                if listing.kind != "completed":
                    self._invalidate(host)
                    self._status = f"host_{listing.kind}"
                    self._diagnostic(f"ADB capability devices status={listing.kind}")
                    return
                restored = not host.available and host.preference is not None
                host.available = True
                self._status = "ready"
                host.next_check = time.monotonic() + self.CHECK_INTERVAL
                self._condition.notify_all()
                self.observe_devices(listing.stdout.decode("utf-8", errors="ignore"))
            if restored:
                self._diagnostic(
                    f"ADB recovery devices fast={self._selected(host)} benchmark=cached"
                )
            self._service_ready()
            self._publish()
            self._probe_backends(path, host, host_epoch, socket_elapsed)
            with self._condition:
                if self._current(host, host_epoch):
                    self._status = "ready"
        finally:
            self._service_ready()

    def _probe_capability(
        self, command: str, args: list[str], *, serial: str | None, retry: bool,
        current: Callable[[], bool], initial_timeout: float | None = None,
    ) -> tuple[ExecutionResult, float]:
        """仅复核只读能力探针；首试与一次重试共用预算，取消和协议拒绝不重试。"""
        deadline = time.monotonic() + self.CAPABILITY_BUDGET
        stop = self._probe_stop.is_set
        started = time.monotonic()
        result = capture(
            command, args, serial=serial,
            timeout=self.SOCKET_TIMEOUT if initial_timeout is None else initial_timeout,
            cancelled=stop,
        )
        elapsed = time.monotonic() - started
        adb_debug.event(
            "probe_result", command=command, backend="server_direct", status=result.kind,
            elapsed_ms=round(elapsed * 1000, 1), client_spawned=False,
        )
        remaining = deadline - time.monotonic()
        if retry and result.kind in {"timeout", "transport"} and not stop() and remaining > 0:
            with self._condition:
                if not current():
                    return result, elapsed
                self._status = "retrying"
            self._diagnostic(f"ADB capability {command} status={result.kind} retry=1")
            self._publish()
            with self._condition:
                # 通知可能让出执行权；重新确认连接归属及剩余预算再准入复核。
                remaining = deadline - time.monotonic()
                if stop() or not current() or remaining <= 0:
                    return result, elapsed
            started = time.monotonic()
            result = capture(
                command, args, serial=serial, timeout=remaining, cancelled=stop,
            )
            elapsed = time.monotonic() - started
            adb_debug.event(
                "probe_result", command=command, backend="server_direct", status=result.kind,
                elapsed_ms=round(elapsed * 1000, 1), retry=1, client_spawned=False,
            )
        return result, elapsed

    def _probe_backends(
        self, path: str, host: _BackendState, host_epoch: int, socket_elapsed: float,
    ) -> None:
        """唯一探测线程优先消费新能力检查；只有只读基准允许抢占后重测。"""
        stop = self._probe_stop.is_set
        checked_states = self._probe_checked
        samples: list[tuple[str, _BackendState, int, ExecutionResult, float]] = []
        with self._condition:
            measure_host = self._full_probe or not host.benchmarked

        def next_target():
            # 由持锁调用方读取拓扑；本轮强制验证每个状态一次，失败仍遵守恢复节流。
            return next((
                (serial, state, state.epoch)
                for serial, state in self._shell.items()
                if id(state) not in checked_states and (
                    self._full_probe
                    or (not state.available and time.monotonic() >= state.next_check)
                )
            ), None)

        def yield_benchmark() -> bool:
            with self._condition:
                return stop() or not self._current(host, host_epoch) or next_target() is not None

        while not stop():
            with self._condition:
                if not self._current(host, host_epoch):
                    return
                target = next_target()
            if target is not None:
                serial, state, epoch = target
                checked_states.add(id(state))
                fast, elapsed = self._probe_capability(
                    "shell", [self.PROBE_COMMAND], serial=serial,
                    retry=self._full_probe or not state.checked,
                    current=lambda: self._current(host, host_epoch)
                    and self._current(state, epoch, serial),
                )
                valid = (
                    fast.kind == "completed" and fast.returncode == 7
                    and fast.stdout == b"ADBLAB_OUT" and fast.stderr == b"ADBLAB_ERR"
                )
                with self._condition:
                    if (
                        not self._current(host, host_epoch)
                        or not self._current(state, epoch, serial)
                    ):
                        continue
                    restored = valid and not state.available and state.preference is not None
                    state.checked = True
                    if valid:
                        state.available = True
                        state.next_check = time.monotonic() + self.CHECK_INTERVAL
                        if self._full_probe or not state.benchmarked:
                            samples.append((serial, state, epoch, fast, elapsed))
                    else:
                        self._invalidate(state)
                    self._condition.notify_all()
                if restored:
                    self._diagnostic(
                        f"ADB recovery shell fast={self._selected(state)} benchmark=cached"
                    )
                elif not valid:
                    self._diagnostic(
                        f"ADB capability shell status={fast.kind} retry_s={self.CHECK_INTERVAL:.0f}"
                    )
                self._publish()
                continue
            if measure_host:
                started = time.monotonic()
                baseline = native_capture(
                    [path, "devices", "-l"], self.PROBE_TIMEOUT, yield_benchmark,
                )
                native_elapsed = time.monotonic() - started
                if stop():
                    return
                if baseline.kind == "cancelled":
                    continue
                selected = (
                    self._prefer_socket(baseline, native_elapsed, socket_elapsed)
                    if baseline.kind == "timeout" or self._valid_listing(baseline) else None
                )
                if selected is False:
                    with self._condition:
                        sample_generation = self._generation
                        if not self._current(host, host_epoch):
                            return
                    # 冷启动样本不能单独证明原生更快；只在准备降级时补一次稳定样本。
                    started = time.monotonic()
                    warm = capture(
                        "devices", ["-l"], serial=None,
                        timeout=self.SOCKET_TIMEOUT, cancelled=yield_benchmark,
                    )
                    warm_elapsed = time.monotonic() - started
                    if warm.kind == "cancelled":
                        continue
                    selected = (
                        self._prefer_socket(baseline, native_elapsed, warm_elapsed)
                        if self._valid_listing(warm) else None
                    )
                    with self._condition:
                        if not self._current(host, host_epoch):
                            return
                        if sample_generation != self._generation:
                            selected = None
                        elif self._valid_listing(warm):
                            self.observe_devices(warm.stdout.decode("utf-8", errors="ignore"))
                        if sample_generation != self._generation:
                            selected = None
                    self._diagnostic(
                        f"ADB benchmark devices warm_ms={warm_elapsed * 1000:.1f} "
                        f"warm_status={warm.kind}"
                    )
                with self._condition:
                    current = self._current(host, host_epoch)
                    if current:
                        host.benchmarked = True
                        if selected is not None:
                            host.preference = selected
                measure_host = False
                self._diagnostic(
                    f"ADB probe devices socket_ms={socket_elapsed * 1000:.1f} "
                    f"native_ms={native_elapsed * 1000:.1f} native_status={baseline.kind} "
                    f"applied={current and selected is not None}"
                )
                continue
            if not samples:
                return
            serial, state, epoch, fast, elapsed = samples[0]
            with self._condition:
                if not self._current(state, epoch, serial):
                    samples.pop(0)
                    continue
            started = time.monotonic()
            baseline = native_capture(
                [path, "-s", serial, "shell", self.PROBE_COMMAND],
                self.PROBE_TIMEOUT, yield_benchmark,
            )
            native_elapsed = time.monotonic() - started
            if stop():
                return
            if baseline.kind == "cancelled":
                continue
            samples.pop(0)
            same = (
                baseline.stdout == fast.stdout and baseline.stderr == fast.stderr
                and baseline.returncode == fast.returncode
            )
            selected = (
                self._prefer_socket(baseline, native_elapsed, elapsed)
                if same or baseline.kind == "timeout" else None
            )
            if selected is False:
                with self._condition:
                    if (
                        not self._current(host, host_epoch)
                        or not self._current(state, epoch, serial)
                    ):
                        continue
                started = time.monotonic()
                warm = capture(
                    "shell", [self.PROBE_COMMAND], serial=serial,
                    timeout=self.SOCKET_TIMEOUT, cancelled=yield_benchmark,
                )
                warm_elapsed = time.monotonic() - started
                if warm.kind == "cancelled":
                    # 新目标抢占时保留这一组基准，避免把取消固化为已经测速。
                    samples.insert(0, (serial, state, epoch, fast, elapsed))
                    continue
                valid = (
                    warm.kind == "completed" and warm.returncode == fast.returncode
                    and warm.stdout == fast.stdout and warm.stderr == fast.stderr
                )
                selected = (
                    self._prefer_socket(baseline, native_elapsed, warm_elapsed) if valid else None
                )
                self._diagnostic(
                    f"ADB benchmark shell warm_ms={warm_elapsed * 1000:.1f} warm_status={warm.kind}"
                )
            with self._condition:
                current = (
                    self._current(host, host_epoch) and self._current(state, epoch, serial)
                )
                if current:
                    state.benchmarked = True
                    if selected is not None:
                        state.preference = selected
            self._diagnostic(
                f"ADB probe shell socket_ms={elapsed * 1000:.1f} "
                f"native_ms={native_elapsed * 1000:.1f} native_status={baseline.kind} "
                f"fast={self._selected(state)} applied={current and selected is not None}"
            )
            self._publish()

    def observe_devices(self, output: str) -> None:
        """按在线设备和 transport_id 更新代次；同数量替换和离线恢复也使能力失效。"""
        topology = {}
        for line in output.splitlines():
            parts = line.split()
            if (
                len(parts) >= 2
                and parts[1] == "device"
                and (self._probe_serial is None or parts[0] == self._probe_serial)
            ):
                topology[parts[0]] = next(
                    (p for p in parts[2:] if p.startswith("transport_id:")), ""
                )
        with self._condition:
            if self._closed or self._draining:
                return
            if topology != self._topology:
                self._generation += 1
                self._shell = {
                    serial: self._shell[serial]
                    if serial in self._shell and fingerprint == self._topology.get(serial)
                    else _BackendState()
                    for serial, fingerprint in topology.items()
                }
                self._topology = topology
                self._condition.notify_all()
            self.request_device_check()

    def can_scan_fast(self) -> bool:
        """允许独立快速扫描；忙碌的普通命令不应延迟设备发现。"""
        with self._condition:
            return (
                not self._closed
                and not self._native_only
                and self._selected(self._host)
                and local_server_environment()
            )

    def can_shell_fast(self, adb_path: str, serial: str) -> bool:
        """只读判断指定路径和当前设备连接能否直连，不触发探测、等待或其他 I/O。

        拓扑更新会替换设备状态，故障会撤销该状态的能力；只从当前映射取值，
        不复用旧连接或展示快照的汇总计数。实际执行仍须经过运行时再次准入。
        """
        with self._condition:
            if (
                self._closed or self._draining or self._native_only
                or not local_server_environment()
                or not self._path or not adb_path or not serial
                or any(ord(char) < 33 or ord(char) == 127 for char in serial)
                or os.path.normcase(os.path.abspath(adb_path))
                != os.path.normcase(os.path.abspath(self._path))
            ):
                return False
            state = self._shell.get(serial)
            return (
                self._host.available
                and serial in self._topology
                and state is not None
                and self._selected(state)
            )

    def request_device_check(self) -> None:
        """扫描和业务入口共用有节流检查，不依赖原生发现成功，也不重做有效基准。"""
        with self._condition:
            if (
                self._native_only or self._draining or self._closed
                or not local_server_environment()
            ):
                return
            now = time.monotonic()
            due = now >= self._host.next_check or (
                self._host.available and any(
                    not state.available and now >= state.next_check
                    for state in self._shell.values()
                )
            )
            if due:
                self.start(force=False)

    def wait_for_device_check(
        self,
        timeout: float,
        cancelled: CancelCheck | None = None,
        *,
        adb_path: str | None = None,
    ) -> ExecutionResult | None:
        """在调用预算内等待发现准入，不执行设备命令，也不等待已就绪服务的测速。

        ``adb_path`` 省略时表示应用默认扫描入口；显式其他路径仍交还原生执行。
        路径尚未发布时先等当前解析，之后重新核对路径和能力。返回 ``None`` 仅表示
        可以重新选择后端；等待中的取消或超时必须直接结束，不能另起原生客户端。
        清理阶段的新调用保留既有准入，只有关闭前已经等待的调用被原停止信号取消。
        """
        deadline = time.monotonic() + timeout
        with self._condition:
            stop = self._request_stop
            requested = False
            while True:
                if self._closed or stop.is_set() or (cancelled is not None and cancelled()):
                    return ExecutionResult(kind="cancelled")
                if self._native_only or self._draining or not local_server_environment():
                    return None
                if adb_path is not None and self._path is not None and os.path.normcase(
                    os.path.abspath(adb_path)
                ) != os.path.normcase(os.path.abspath(self._path)):
                    return None
                if not requested and (adb_path is None or self._path is not None):
                    self.request_device_check()
                    requested = True
                if not self._checking or (self._path is not None and self._host.available):
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ExecutionResult(kind="timeout")
                # 释放锁让唯一探测提交结果；外部取消信号最多延迟一个轮询片段。
                self._condition.wait(min(0.1, remaining))

    def _parse(
        self, cmd: list[str], *, binary: bool = False,
    ) -> tuple[str, list[str], str | None] | None:
        if not self._path or os.path.normcase(os.path.abspath(cmd[0])) != os.path.normcase(
            os.path.abspath(self._path)
        ):
            return None
        args = cmd[1:]
        serial = os.environ.get("ANDROID_SERIAL") or None
        if len(args) >= 2 and args[0] == "-s":
            serial, args = args[1], args[2:]
        if binary:
            # 只映射已验证的截图命令，不能将任意 exec-out 改成设备 shell。
            if args != ["exec-out", "screencap", "-p"]:
                return None
            args = ["shell", "screencap", "-p"]
        if args in (["devices"], ["devices", "-l"]):
            return "devices", args[1:], None
        if (
            len(args) >= 2
            and args[0] == "shell"
            and serial
            and not args[1].startswith("-")
            and " ".join(args[1:]).strip()
            and not any(ord(c) < 33 or ord(c) == 127 for c in serial)
        ):
            return "shell", args[1:], serial
        return None

    def try_run(
        self,
        cmd: list[str],
        timeout: float,
        cancelled: CancelCheck | None = None,
        *,
        stdout_sink: BinaryIO | None = None,
    ) -> ExecutionResult | None:
        """返回适配结果或发送前的原生选择；连接建立后的故障绝不回退重放。

        成功设备列表若已被更新的拓扑或能力代次取代，返回 ``stale`` 且不携带旧列表；
        这不表示连接失败，已完成的业务 Shell 结果仍按原始输出和退出码交付。
        """
        deadline = time.monotonic() + timeout
        with self._condition:
            if self._closed:
                return ExecutionResult(kind="cancelled")
            args = cmd[3:] if len(cmd) >= 3 and cmd[1] == "-s" else cmd[1:]
            if stdout_sink is None and args in (["devices"], ["devices", "-l"]):
                admission = self.wait_for_device_check(
                    max(0, deadline - time.monotonic()), cancelled, adb_path=cmd[0],
                )
                if admission is not None:
                    return admission
            parsed = (
                self._parse(cmd, binary=stdout_sink is not None)
                if cmd and local_server_environment() else None
            )
            if parsed is None or self._native_only:
                return None
            if cancelled is not None and cancelled():
                return ExecutionResult(kind="cancelled")
            command, args, serial = parsed
            event = self._request_stop
            self.request_device_check()
            # 初次元数据请求可能先于能力信号到达；只在后台短等已排队的验证，
            # 避免已知慢环境的首轮查询立即退回原生。等待仍属于原命令预算。
            ready_deadline = min(deadline, time.monotonic() + 0.5)
            wait_started = time.monotonic()
            waited = False
            # 新设备可能尚未出现在本轮 listing 的拓扑里：先在共享短预算内等一次列表，
            # 避免刚插入设备的第一条 shell 命令必然回退原生。
            while (
                command == "shell"
                and bool(serial)
                and serial not in self._topology
                and self._checking
                and not self._draining
                and not self._native_only
            ):
                if cancelled is not None and cancelled():
                    return ExecutionResult(kind="cancelled")
                remaining = ready_deadline - time.monotonic()
                if remaining <= 0:
                    break
                waited = True
                self._condition.wait(min(0.1, remaining))
            while (
                command == "shell"
                and (pending := self._shell.get(serial or "")) is not None
                and not pending.available
                and time.monotonic() >= pending.next_check
                and self._checking
                and not self._draining
                and not self._native_only
            ):
                if cancelled is not None and cancelled():
                    return ExecutionResult(kind="cancelled")
                remaining = ready_deadline - time.monotonic()
                if remaining <= 0:
                    break
                waited = True
                self._condition.wait(min(0.1, remaining))
            if self._closed or event.is_set():
                return ExecutionResult(kind="cancelled")
            if time.monotonic() >= deadline:
                return ExecutionResult(kind="timeout")
            if self._native_only:
                return None
            host = self._host
            host_epoch = host.epoch
            state = host if command == "devices" else self._shell.get(serial or "")
            selected = state is not None and self._selected(state) and host.available
            epoch = state.epoch if state is not None else 0
            generation = self._generation
            if selected:
                self._active += 1
            selection_mode = self._mode
        if not selected or state is None:
            if waited:
                self._diagnostic(
                    f"ADB select command={command} backend=native "
                    f"wait_ms={(time.monotonic() - wait_started) * 1000:.1f}"
                )
            return None
        try:
            if waited:
                self._diagnostic(
                    f"ADB select command={command} backend=socket "
                    f"wait_ms={(time.monotonic() - wait_started) * 1000:.1f}"
                )
            sink_options = {"stdout_sink": stdout_sink} if stdout_sink is not None else {}
            adb_debug.command(
                cmd, backend="server_direct", selection_mode=selection_mode,
                endpoint="127.0.0.1:5037", client_spawned=False,
            )
            result = capture(
                command,
                args,
                serial=serial,
                timeout=max(0.001, deadline - time.monotonic()),
                cancelled=lambda: event.is_set() or bool(cancelled and cancelled()),
                **sink_options,
            )
            if adb_debug.enabled():
                adb_debug.command(
                    cmd, backend="server_direct", phase="finish", status=result.kind,
                    returncode=result.returncode, client_spawned=False,
                )
            failed = result.kind in {"unavailable", "protocol", "transport"}
            with self._condition:
                current = (
                    self._current(host, host_epoch)
                    and self._current(state, epoch, serial)
                    and (command != "devices" or generation == self._generation)
                )
                if (
                    not current and command == "devices"
                    and result.kind == "completed" and result.returncode == 0
                ):
                    # 内部拒收还不够：外部扫描也必须识别旧结果，避免回滚已发布设备。
                    return ExecutionResult(kind="stale")
                if current and failed:
                    self._invalidate(state)
                    self._status = f"host_{result.kind}" if state is host else "shell_unavailable"
                elif (
                    current and result.kind == "completed"
                    and command == "devices" and args == ["-l"]
                ):
                    self.observe_devices(result.stdout.decode("utf-8", errors="ignore"))
            if failed:
                if not current:
                    return result
                self._diagnostic(
                    f"ADB unavailable command={command} status={result.kind} "
                    f"retry_s={self.CHECK_INTERVAL:.0f}"
                )
                self._publish()
            if (
                result.kind == "unavailable"
                and not event.is_set()
                and not (cancelled and cancelled())
            ):
                return None
            return result
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def prepare_shutdown(self) -> None:
        """停止探测并取消已有请求；随后进入的必要清理由新一代停止信号管理。"""
        with self._condition:
            if self._draining:
                return
            self._draining = True
            self._probe_stop.set()
            self._request_stop.set()
            self._request_stop = threading.Event()
            self._condition.notify_all()

    def close(self) -> None:
        """最终封闭并取消所有快速请求；调用方继续通过 wait 确认资源实际退出。"""
        self.prepare_shutdown()
        with self._condition:
            self._closed = True
            self._request_stop.set()
            self._condition.notify_all()

    def is_running(self) -> bool:
        """包含探测线程的实际存活状态，不以取消请求代替退出确认。"""
        with self._condition:
            return self._active > 0 or bool(self._thread and self._thread.is_alive())

    def wait(self, timeout: float) -> bool:
        """在共享预算内等待探测和活动请求结束，不阻塞 GUI 调用方。"""
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(max(0, deadline - time.monotonic()))
        with self._condition:
            while self._active and time.monotonic() < deadline:
                self._condition.wait(max(0, deadline - time.monotonic()))
        return not self.is_running()
