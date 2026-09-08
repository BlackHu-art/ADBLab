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
                        return ExecutionResult(kind="cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return ExecutionResult(kind="timeout")
                    try:
                        out, err = proc.communicate(timeout=min(0.1, remaining))
                        return ExecutionResult(out or b"", err, proc.returncode)
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
    except OSError:
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


@dataclass
class _BackendState:
    """把当前可用性与本次连接的测速偏好分开，短暂故障不丢失有效基准。"""

    available: bool = False
    preference: bool | None = None
    checked: bool = False
    next_check: float = 0.0
    epoch: int = 0

    @property
    def fast(self) -> bool:
        """首次能力通过即可使用直连；已知原生更快时保留原生选择。"""
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
        self._host = _BackendState()
        self._shell: dict[str, _BackendState] = {}
        self._topology: dict[str, str] = {}
        self._generation = 0
        self._active = 0
        self._path: str | None = None
        self._ready_sent = False
        self._full_probe = True
        self._bootstrap_pending = True
        self._allow_bootstrap = False

    def snapshot(self) -> RuntimeSnapshot:
        """原子读取当前能力状态，不暴露可变策略。"""
        with self._condition:
            return RuntimeSnapshot(
                self._checking,
                self._host.available,
                self._native_only,
                self._host.fast and not self._native_only,
                sum(state.fast for state in self._shell.values()) if not self._native_only else 0,
                sum(state.checked for state in self._shell.values()),
            )

    def _publish(self) -> None:
        if self._probe_stop.is_set():
            return
        self._changed(self.snapshot())

    def start(self, *, force: bool = True) -> bool:
        """启动唯一探测任务；仅首次初始化可启动服务，强制重测不重启服务。"""
        with self._condition:
            if (
                self._closed
                or self._draining
                or self._checking
                or (self._native_only and not force)
            ):
                return False
            self._checking = True
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

    def set_native_only(self, enabled: bool) -> None:
        """只改变后续调用的选择，不停止已发送请求，也不写入持久配置。"""
        with self._condition:
            self._native_only = bool(enabled)
            self._condition.notify_all()
        self._publish()

    def _service_ready(self) -> None:
        with self._condition:
            first = not self._ready_sent
            self._ready_sent = True
        if first and not self._probe_stop.is_set():
            self._ready()

    @staticmethod
    def _prefer_socket(native: ExecutionResult, elapsed: float, socket_elapsed: float) -> bool:
        # 原生探针达到时限只提供耗时下界，不说明设备故障。
        if native.kind == "timeout":
            return socket_elapsed < elapsed * 0.8
        return native.kind == "completed" and socket_elapsed + 0.02 < elapsed * 0.8

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
                            not state.available and time.monotonic() >= state.next_check
                            for state in self._shell.values()
                        )
                    ):
                        # 收尾期间接到的新目标由当前线程继续处理，不依赖下一次扫描。
                        self._full_probe = False
                        continue
                    self._checking = False
                    self._condition.notify_all()
                    return
        finally:
            self._service_ready()
            with self._condition:
                # 新一轮可能已取得准入并在 join 当前线程，旧收尾不能清除其 checking。
                if self._thread is threading.current_thread():
                    self._checking = False
                    self._condition.notify_all()
                    self._publish()

    def _probe_once(self) -> None:
        try:
            self._publish()
            path = self._resolver()
            with self._condition:
                if self._draining:
                    return
                if path != self._path or not local_server_environment():
                    self._host = _BackendState()
                    self._shell.clear()
                    self._topology.clear()
                    self._generation += 1
                self._path = path
                host = self._host
                host_epoch = host.epoch
                generation = self._generation
                host.next_check = time.monotonic() + self.CHECK_INTERVAL
            if not path or not local_server_environment():
                return
            stop = self._probe_stop.is_set
            start = time.monotonic()
            listing = capture(
                "devices", ["-l"], serial=None, timeout=self.SOCKET_TIMEOUT, cancelled=stop
            )
            if listing.kind == "unavailable" and self._allow_bootstrap and not stop():
                native_capture([path, "start-server"], 15.0, stop)
                start = time.monotonic()
                listing = capture(
                    "devices", ["-l"], serial=None, timeout=self.SOCKET_TIMEOUT, cancelled=stop
                )
            socket_elapsed = time.monotonic() - start
            with self._condition:
                if not self._current(host, host_epoch) or generation != self._generation:
                    return
                host.checked = True
                if listing.kind != "completed":
                    self._invalidate(host)
                    return
                restored = not host.available and host.preference is not None
                host.available = True
                host.next_check = time.monotonic() + self.CHECK_INTERVAL
                self.observe_devices(listing.stdout.decode("utf-8", errors="ignore"))
            if restored:
                self._diagnostic(f"ADB recovery devices fast={host.fast} benchmark=cached")
            self._service_ready()
            self._publish()
            self._probe_backends(path, host, host_epoch, socket_elapsed)
        finally:
            self._service_ready()

    def _probe_backends(
        self, path: str, host: _BackendState, host_epoch: int, socket_elapsed: float,
    ) -> None:
        """唯一探测线程优先消费新能力检查；只有只读基准允许抢占后重测。"""
        stop = self._probe_stop.is_set
        checked_states: set[int] = set()
        samples: list[tuple[str, _BackendState, int, ExecutionResult, float]] = []
        with self._condition:
            measure_host = self._full_probe or host.preference is None

        def next_target():
            # 由持锁调用方读取拓扑；本轮强制验证每个状态一次，失败仍遵守恢复节流。
            return next((
                (serial, state, state.epoch)
                for serial, state in self._shell.items()
                if (self._full_probe and id(state) not in checked_states)
                or (not state.available and time.monotonic() >= state.next_check)
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
                started = time.monotonic()
                fast = capture(
                    "shell", [self.PROBE_COMMAND], serial=serial,
                    timeout=self.SOCKET_TIMEOUT, cancelled=stop,
                )
                elapsed = time.monotonic() - started
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
                        if self._full_probe or state.preference is None:
                            samples.append((serial, state, epoch, fast, elapsed))
                    else:
                        self._invalidate(state)
                    self._condition.notify_all()
                if restored:
                    self._diagnostic(f"ADB recovery shell fast={state.fast} benchmark=cached")
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
                with self._condition:
                    current = self._current(host, host_epoch)
                    if current:
                        host.preference = self._prefer_socket(
                            baseline, native_elapsed, socket_elapsed,
                        )
                measure_host = False
                self._diagnostic(
                    f"ADB probe devices socket_ms={socket_elapsed * 1000:.1f} "
                    f"native_ms={native_elapsed * 1000:.1f} native_status={baseline.kind} "
                    f"applied={current}"
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
            selected = (same or baseline.kind == "timeout") and self._prefer_socket(
                baseline, native_elapsed, elapsed,
            )
            with self._condition:
                current = (
                    self._current(host, host_epoch) and self._current(state, epoch, serial)
                )
                if current:
                    state.preference = selected
            self._diagnostic(
                f"ADB probe shell socket_ms={elapsed * 1000:.1f} "
                f"native_ms={native_elapsed * 1000:.1f} native_status={baseline.kind} "
                f"fast={selected} applied={current}"
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
                and self._host.fast
                and local_server_environment()
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
            selected = state is not None and state.fast
            epoch = state.epoch if state is not None else 0
            generation = self._generation
            if selected:
                self._active += 1
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
            result = capture(
                command,
                args,
                serial=serial,
                timeout=max(0.001, deadline - time.monotonic()),
                cancelled=lambda: event.is_set() or bool(cancelled and cancelled()),
                **sink_options,
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
