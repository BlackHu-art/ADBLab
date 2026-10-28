"""在 Qt 主进程与内置 MobilePerf 命令行采集器之间提供进程隔离适配。"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from core.adb_runtime import AdbRuntime
from core.exec import ExecHandle, ProcessRunner, adb_runtime
from core.owned_process import OwnedWorkerProcess
from services.performance.config import (
    MobilePerfMonkeyConfig as MobilePerfMonkeyConfig,
)
from services.performance.config import (
    MobilePerfRunConfig as MobilePerfRunConfig,
)
from services.performance.config import (
    _normalize_package as _normalize_package,
)
from services.performance.config import (
    _primary_package as _primary_package,
)
from services.performance.config import (
    _split_semicolon as _split_semicolon,
)
from services.performance.config import (
    normalize_local_path as normalize_local_path,
)
from services.performance.results import (
    PerformanceArtifacts as PerformanceArtifacts,
)
from services.performance.results import (
    PerformanceResultQuery as PerformanceResultQuery,
)
from services.performance.results import (
    path_key,
)
from utils.console_colors import colorize_console, should_emit
from utils.resource_path import resource_path
from utils.user_data import user_data_root

# 结果目录中的包名片段仅允许字母数字、点、下划线和连字符，其余字符替换为下划线。
_RESULT_SEGMENT_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(slots=True)
class _MobilePerfRunContext:
    """保存单次 MobilePerf 运行中不得跨代复用的进程和回调状态。"""

    generation: int
    process_key: str
    proc: ExecHandle
    config: MobilePerfRunConfig
    redaction_values: tuple[str, ...]
    on_log: Callable[[str], None] | None
    on_finished: Callable[[], None] | None
    config_dir: tempfile.TemporaryDirectory[str]
    config_path: str
    stop_path: str
    mode_path: str
    mode_stop: threading.Event = field(default_factory=threading.Event)
    mode_done: threading.Event = field(default_factory=threading.Event)
    stdout_done: threading.Event = field(default_factory=threading.Event)
    stderr_done: threading.Event = field(default_factory=threading.Event)
    finish_lock: threading.Lock = field(default_factory=threading.Lock)
    tracking_lock: threading.Lock = field(default_factory=threading.Lock)
    log_thread: threading.Thread | None = None
    diagnostic_thread: threading.Thread | None = None
    mode_thread: threading.Thread | None = None
    exit_code: int | None = None
    finished_notified: bool = False
    config_cleaned: bool = False
    process_tracking_released: bool = False
    threads_submitted: bool = False
    log_lock: threading.RLock = field(default_factory=threading.RLock)
    pending_logs: list[str] = field(default_factory=list)
    last_log_flush: float = field(default_factory=time.monotonic)


class MobilePerfRunner:
    """在与 Qt 应用隔离的子进程中启动、停止并跟踪 MobilePerf。"""

    LOG_BATCH_SIZE = 50
    LOG_BATCH_INTERVAL_SECONDS = 0.2
    PIPE_EXIT_POLL_SECONDS = 1.0
    MODE_SYNC_INTERVAL_SECONDS = 0.1
    REPORT_SHUTDOWN_TIMEOUT_SECONDS = 90.0
    _DEBUG_RECORD_PATTERN = re.compile(r"^\[[^\]]+\]DEBUG:mobileperf:")
    _DIAGNOSTIC_LEVEL_PATTERN = re.compile(
        r"^\[[^\]]+\](DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL):mobileperf:"
    )

    def __init__(
        self,
        *,
        process_runner: ProcessRunner | None = None,
        project_root: str | os.PathLike[str] | None = None,
        python_executable: str | None = None,
    ):
        self._process_runner = process_runner or ProcessRunner()
        self._project_root = Path(project_root or self._default_project_root())
        self._python_executable = python_executable or sys.executable
        self._process_key_prefix = f"mobileperf_{id(self)}"
        self._process_key = self._process_key_prefix
        self._proc: ExecHandle | None = None
        self._config_dir: tempfile.TemporaryDirectory[str] | None = None
        self._config_path: str = ""
        self._stop_path: str = ""
        self._diagnostic_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._generation = 0
        self._active_context: _MobilePerfRunContext | None = None
        self._latest_context: _MobilePerfRunContext | None = None
        self._residual_contexts: list[_MobilePerfRunContext] = []
        self._mode_contexts: list[_MobilePerfRunContext] = []
        self._resource_contexts: list[_MobilePerfRunContext] = []
        self._last_config: MobilePerfRunConfig | None = None
        self._metadata_run_id = ""
        self._last_exit_code: int | None = None
        self._baseline_package_root = ""
        self._baseline_result_dirs: dict[str, tuple[int, int]] = {}
        self._baseline_reports: dict[str, tuple[int, int]] = {}

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def last_config(self) -> MobilePerfRunConfig | None:
        return self._last_config

    @property
    def last_exit_code(self) -> int | None:
        if self._last_exit_code is None and self._proc is not None:
            exit_code = self._proc.poll()
            if exit_code is not None:
                self._last_exit_code = exit_code
        return self._last_exit_code

    def is_running(self) -> bool:
        """保持业务重启判断；管道排空与关闭监督使用独立资源接口。"""
        with self._state_lock:
            self._mode_contexts = [
                context for context in self._mode_contexts
                if context.mode_thread is not None and context.mode_thread.is_alive()
            ]
            return bool(self._mode_contexts) or (
                self._proc is not None and self._proc.poll() is None
            )

    @staticmethod
    def _context_resources_active(context: _MobilePerfRunContext) -> bool:
        """线程提交前仍保留义务，完成事件不能替代线程实际退出。"""
        return (
            not context.threads_submitted
            or context.proc.poll() is None
            or (isinstance(context.proc, OwnedWorkerProcess)
                and not context.proc.resources_released())
            or any(thread is not None and thread.is_alive() for thread in (
                context.log_thread, context.diagnostic_thread, context.mode_thread,
            ))
        )

    def has_active_resources(self) -> bool:
        """检查所有未排空代次的进程、客户端和真实 reader/writer 线程。"""
        with self._state_lock:
            self._resource_contexts = [
                context for context in self._resource_contexts
                if self._context_resources_active(context)
            ]
            return bool(self._resource_contexts or self._residual_contexts) or (
                self._proc is not None and self._proc.poll() is None
            )

    def is_current_run_complete(self) -> bool:
        """最近代次的完成回调和真实线程均退出后才交付报告，不等待旧代资源。"""
        with self._state_lock:
            context = self._latest_context
            return context is None or (
                context.finished_notified and context.threads_submitted
                and context.proc.poll() is not None
                and all(thread is None or not thread.is_alive() for thread in (
                    context.log_thread, context.diagnostic_thread, context.mode_thread,
                ))
            )

    def wait(self, timeout: float) -> bool:
        """在共同预算内等待调用时已归属的全部代次，超时继续保留资源。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._state_lock:
            contexts = tuple(self._resource_contexts)
        for context in contexts:
            self._join_context_readers(context, timeout=max(0.0, deadline - time.monotonic()))
        return not self.has_active_resources()

    def start(
        self,
        config: MobilePerfRunConfig,
        *,
        on_log: Callable[[str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """同步准备并启动；取消在准备边界阻止创建进程，已进入创建的进程由调用方收口。

        on_log/on_finished 可能由管道 reader 或模式线程调用，异常会被隔离，但回调不得
        阻塞，也不得直接操作 Qt 控件；启动返回只代表进程已提交，结束由 on_finished 确认。
        """
        if cancelled is not None and cancelled():
            raise CancelledError
        with self._state_lock:
            # 已退出进程的旧代写入可独立收尾；新运行使用不同路径，仍由监督接口保留旧资源。
            if self._residual_contexts:
                raise RuntimeError("Previous Monkey cleanup is not confirmed")
            current_proc = (
                self._active_context.proc if self._active_context is not None else self._proc
            )
            if current_proc is not None and current_proc.poll() is None:
                raise RuntimeError("mobileperf is already running")
            if (
                isinstance(current_proc, OwnedWorkerProcess)
                and not current_proc.resources_released()
            ):
                raise RuntimeError("Previous Monkey cleanup is not confirmed")
            config = self._resolved_run_config(config)
            self._prepare_result_root(Path(config.save_path))
            self._generation += 1
            generation = self._generation
            process_key = f"{self._process_key_prefix}_{generation}"
            self._process_key = process_key
            self._last_config = config
            self._metadata_run_id = uuid4().hex
            self._last_exit_code = None
            self._capture_result_baseline(config)
            if cancelled is not None and cancelled():
                raise CancelledError
            config_dir = tempfile.TemporaryDirectory(prefix="adblab_mobileperf_")
            self._config_dir = config_dir
            proc = None
            try:
                self._config_path = config.write_config(config_dir.name)
                self._stop_path = os.path.join(config_dir.name, "mobileperf.stop")
                cmd = self._build_command()
                env = os.environ.copy()
                # 源码 -m worker 直接沿用解释器标准流，编码必须与父进程 reader 一致。
                env["PYTHONIOENCODING"] = "utf-8"
                runtime = adb_runtime()
                mode = runtime.snapshot().selection_mode if runtime is not None else "auto"
                mode_path = os.path.join(config_dir.name, "mobileperf.adb-mode")
                # 模式文件只属于本次运行，设备能力仍由子进程独立校验。
                env["MOBILEPERF_ADB_MODE"] = mode
                env["MOBILEPERF_ADB_MODE_FILE"] = mode_path
                adb_path = self._resolve_adb_path()
                env["ADB_PATH"] = adb_path
                env["MOBILEPERF_STOP_FILE"] = self._stop_path
                env["MOBILEPERF_RUN_ID"] = self._metadata_run_id
                env["MOBILEPERF_LOG_DIR"] = str(user_data_root() / "logs")
                redaction_values = tuple(
                    self._sensitive_runtime_values(
                        config,
                        config_path=self._config_path,
                        stop_path=self._stop_path,
                    )
                )
                env["MOBILEPERF_REDACT_VALUES"] = json.dumps(
                    redaction_values,
                    ensure_ascii=True,
                )
                (Path(config_dir.name) / "clients").mkdir()
                if cancelled is not None and cancelled():
                    raise CancelledError
                proc = self._process_runner.start(
                    process_key,
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(self._project_root),
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    bufsize=1,
                    env=env,
                    owned_clients_dir=str(Path(config_dir.name) / "clients"),
                )
                if isinstance(proc, OwnedWorkerProcess):
                    proc.hold_cleanup_owner(config_dir)
            except Exception:
                # 进程一旦创建就属于 ProcessRunner 跟踪；不能只删配置目录，
                # 否则 collector 成为无 owner 的孤儿。先停止并确认，再清理配置。
                stopped = True
                if proc is not None:
                    try:
                        stopped = self._process_runner.stop(process_key, timeout=2) is not None
                    except Exception:
                        stopped = False
                if stopped:
                    config_dir.cleanup()
                    self._config_dir = None
                    self._config_path = ""
                    self._stop_path = ""
                raise
            context = _MobilePerfRunContext(
                generation=generation,
                process_key=process_key,
                proc=proc,
                config=config,
                redaction_values=redaction_values,
                on_log=on_log,
                on_finished=on_finished,
                config_dir=config_dir,
                config_path=self._config_path,
                stop_path=self._stop_path,
                mode_path=mode_path,
            )
            self._active_context = context
            self._latest_context = context
            self._resource_contexts.append(context)
            self._proc = proc
            context.mode_thread = threading.Thread(
                target=self._sync_adb_mode,
                args=(context, runtime, mode),
                name=f"adblab-mobileperf-mode-{generation}",
                daemon=False,
            )
            self._mode_contexts.append(context)
            try:
                context.mode_thread.start()
                diagnostic_stream = getattr(proc, "stderr", None)
                if diagnostic_stream is not None:
                    try:
                        iter(diagnostic_stream)
                    except TypeError:
                        diagnostic_stream = None
                if diagnostic_stream is None:
                    context.stderr_done.set()
                context.log_thread = threading.Thread(
                    target=self._read_logs,
                    args=(context,),
                    name=f"adblab-mobileperf-log-{generation}",
                    daemon=True,
                )
                if diagnostic_stream is not None:
                    context.diagnostic_thread = threading.Thread(
                        target=self._read_diagnostics,
                        args=(context,),
                        name=f"adblab-mobileperf-diagnostic-{generation}",
                        daemon=True,
                    )
                context.log_thread.start()
                if context.diagnostic_thread is not None:
                    context.diagnostic_thread.start()
            except Exception:
                # 已提交的线程仍由原代次持有；未提交者撤回义务，避免永久 pending。
                context.on_finished = None
                context.mode_stop.set()
                for thread, done in (
                    (context.mode_thread, context.mode_done),
                    (context.log_thread, context.stdout_done),
                    (context.diagnostic_thread, context.stderr_done),
                ):
                    if thread is None or thread.ident is None:
                        done.set()
                context.threads_submitted = True
                self.stop(timeout=2.0)
                raise
            context.threads_submitted = True
        self._safe_write_diagnostic(
            f"MobilePerf worker started: diagnostic_reader={diagnostic_stream is not None}",
            context,
        )
        return self.expected_result_root(config)

    @staticmethod
    def _write_adb_mode(path: str, mode: str) -> None:
        """同目录原子发布有界模式文本，避免子进程读到截断内容。"""
        temporary = f"{path}.tmp"
        Path(temporary).write_text(mode, encoding="utf-8")
        os.replace(temporary, path)

    def _sync_adb_mode(
        self, context: _MobilePerfRunContext, runtime: AdbRuntime | None, mode: str,
    ) -> None:
        """同步命令策略并限时派发日志；循环和回调均归本运行的关闭屏障拥有。"""
        write_failed = False
        published: str | None = None
        try:
            while not context.mode_stop.is_set() and context.proc.poll() is None:
                selected = runtime.snapshot().selection_mode if runtime is not None else mode
                if selected != published:
                    try:
                        self._write_adb_mode(context.mode_path, selected)
                    except OSError as exc:
                        if not write_failed:
                            self._safe_write_diagnostic(
                                f"MobilePerf ADB mode sync failed: {type(exc).__name__}", context,
                            )
                        write_failed = True
                    else:
                        published = selected
                        write_failed = False
                self._flush_logs(context)
                if context.mode_stop.wait(self.MODE_SYNC_INTERVAL_SECONDS):
                    return
        finally:
            # 模式线程完成最后一次写入后才允许清理目录，仍由原有完成屏障汇合。
            self._mark_reader_done(context, context.mode_done)

    def stop(self, timeout: float = REPORT_SHUTDOWN_TIMEOUT_SECONDS) -> int | None:
        """在共同截止时间内停止调用时的代次，超时仍保留进程及线程归属。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._state_lock:
            context = self._active_context
            proc = context.proc if context is not None else self._proc
            process_key = context.process_key if context is not None else self._process_key
            contexts = tuple(self._resource_contexts)
        code: int | None = None
        if proc is not None:
            if proc.poll() is None:
                self._request_stop_context(context)
                try:
                    proc.wait(timeout=max(0.0, deadline - time.monotonic()))
                    code = proc.returncode
                    self._release_process_tracking(context, process_key, timeout=0)
                except subprocess.TimeoutExpired:
                    code = self._release_process_tracking(
                        context, process_key, timeout=max(0.0, deadline - time.monotonic()),
                    )
            else:
                code = proc.returncode
                self._release_process_tracking(context, process_key, timeout=0)
            if context is not None and code is not None:
                context.exit_code = code
                context.mode_stop.set()
            with self._state_lock:
                if code is not None and (context is None or self._active_context is context):
                    self._last_exit_code = code
                    self._proc = None
        for owned in contexts:
            if owned.proc.poll() is not None:
                owned.mode_stop.set()
                if owned is not context:
                    self._release_process_tracking(
                        owned, owned.process_key,
                        timeout=max(0.0, deadline - time.monotonic()),
                    )
                if owned.process_tracking_released:
                    with self._state_lock:
                        self._residual_contexts = [
                            item for item in self._residual_contexts if item is not owned
                        ]
                    self._maybe_notify_finished(owned)
                    if owned.finished_notified:
                        self._cleanup_run_context(owned)
            self._join_context_readers(
                owned, timeout=max(0.0, deadline - time.monotonic()),
            )
        if context is None and code is not None:
            self._cleanup_config_dir()
        self._safe_write_diagnostic(f"MobilePerf stop finished: exit_code={code}", context)
        return code

    def request_stop(self):
        """写入停止文件，让采集内核在自身清理流程中结束。"""
        with self._state_lock:
            context = self._active_context
        self._request_stop_context(context)

    def _request_stop_context(self, context: _MobilePerfRunContext | None) -> None:
        stop_path = context.stop_path if context is not None else self._stop_path
        if not stop_path:
            return
        Path(stop_path).write_text("stop", encoding="utf-8")

    def force_stop(self, timeout: float = 2.0) -> bool:
        """在调用方给定的总时限内强制停止被跟踪的 MobilePerf 进程。"""
        with self._state_lock:
            context = self._active_context
            process_key = context.process_key if context is not None else self._process_key
        return self._process_runner.force_stop(
            process_key,
            timeout=max(0.0, float(timeout)),
        )

    def _resolved_run_config(self, config: MobilePerfRunConfig) -> MobilePerfRunConfig:
        """返回独立运行快照，固定用户目录基准，不改变原配置或序列化。

        只做词法规范化，不访问文件系统；Windows 的隐含盘符或工作目录不能参与
        输出归属。结果冻结也复用本规则，不能在 GUI 线程触发路径解析 I/O。
        """
        resolved = deepcopy(config)
        value = resolved.result_root
        root = Path(value) if value else Path.home() / "ADBLab" / "mobileperf"
        if os.name == "nt" and (root.drive or root.root) and not root.is_absolute():
            raise ValueError("输出目录须为完整绝对路径或不含盘符的相对路径")
        if not root.is_absolute():
            root = Path.home() / "ADBLab" / root
        resolved.save_path = os.path.normpath(root)
        return resolved

    def _prepare_result_root(self, root: Path) -> None:
        """后台预检安装目录边界和可写性，成功后才允许分配运行资源及创建 worker。"""
        if self._is_frozen():
            protected = [self._project_root]
            executable = Path(self._python_executable)
            if executable.is_absolute():
                protected.append(executable.parent)
            resources = getattr(sys, "_MEIPASS", None)
            if resources:
                protected.append(Path(resources))
            target = root.resolve()
            if any(target.is_relative_to(directory.resolve()) for directory in protected):
                raise ValueError("输出目录不能位于应用安装或资源目录内，请选择用户目录")
        root.mkdir(parents=True, exist_ok=True)
        # 仅创建目录不能证明可写；探针由上下文清理，失败时尚未分配运行临时资源。
        with tempfile.TemporaryFile(dir=root, prefix=".adblab_write_") as probe:
            probe.write(b"1")
            probe.flush()

    def expected_result_root(self, config: MobilePerfRunConfig | None = None) -> str:
        """使用与 worker 配置相同的解析规则预测输出，查询本身不创建目录。"""
        cfg = config or self._last_config or MobilePerfRunConfig()
        return self._resolved_run_config(cfg).save_path

    def latest_result_dir(self, config: MobilePerfRunConfig | None = None) -> str:
        cfg = config or self._last_config
        root = self._package_result_root(cfg)
        if not root.exists():
            return ""
        dirs = [path for path in root.iterdir() if path.is_dir()]
        baseline_dirs, baseline_reports = self._result_baseline_for(root)
        dirs = [
            path
            for path in dirs
            if self._path_signature(path) != baseline_dirs.get(self._path_key(path))
            or self._contains_current_report(path, baseline_reports)
        ]
        if not dirs:
            return ""
        return str(max(dirs, key=lambda path: path.stat().st_mtime))

    def freeze_result_query(self) -> PerformanceResultQuery:
        """只复制运行归属，不执行 I/O；结果发现由页面监督的后台任务完成。"""
        with self._state_lock:
            root = self._package_result_root(self._last_config)
            directories, reports = self._result_baseline_for(root)
            return PerformanceResultQuery(
                str(root), tuple(directories.items()), tuple(reports.items()),
                run_id=self._metadata_run_id,
            )

    def latest_report_file(
        self, config: MobilePerfRunConfig | None = None, *, result_dir: str | None = None,
    ) -> str:
        """按本次目录快照找有效新报告；未提供目录时保持独立发现，空字符串表示无结果。"""
        if result_dir is None:
            result_dir = self.latest_result_dir(config)
        if not result_dir:
            return ""
        reports = glob.glob(os.path.join(result_dir, "summary_*.xlsx"))
        root = self._package_result_root(config or self._last_config)
        _, baseline_reports = self._result_baseline_for(root)
        reports = [
            report
            for report in reports
            if self._is_current_valid_report(Path(report), baseline_reports)
        ]
        if not reports:
            return ""
        return max(reports, key=os.path.getmtime)

    def _read_logs(self, context: _MobilePerfRunContext):
        """排空所属运行的 stdout，并按批次转发业务输出。"""
        proc = context.proc
        stream = getattr(proc, "stdout", None)
        if stream is None:
            self._mark_reader_done(context, context.stdout_done)
            return
        try:
            for line in stream:
                text = line.rstrip("\r\n")
                if not text:
                    continue
                # 子进程协议约定 DEBUG 使用 stderr；此处额外拦截误写 stdout 的诊断记录。
                if self._DEBUG_RECORD_PATTERN.match(text):
                    self._safe_write_diagnostic(text, context)
                    continue
                with context.log_lock:
                    context.pending_logs.append(text)
                    self._flush_logs(context)
        except Exception as exc:
            self._safe_write_diagnostic(
                f"MobilePerf stdout reader failed: {type(exc).__name__}",
                context,
            )
        finally:
            self._flush_logs(context, force=True)
            try:
                stream.close()
            except Exception:
                pass
            self._mark_reader_done(context, context.stdout_done)

    def _flush_logs(self, context: _MobilePerfRunContext, *, force: bool = False) -> None:
        """按数量或时间串行派发；回调完成后才释放锁，防止跨线程乱序和提前终态。"""
        with context.log_lock:
            if not context.pending_logs:
                return
            now = time.monotonic()
            if (
                not force and len(context.pending_logs) < self.LOG_BATCH_SIZE
                and now - context.last_log_flush < self.LOG_BATCH_INTERVAL_SECONDS
            ):
                return
            payload = "\n".join(context.pending_logs)
            context.pending_logs.clear()
            context.last_log_flush = now
            if context.on_log is not None:
                try:
                    context.on_log(payload)
                except Exception as exc:
                    self._safe_write_diagnostic(
                        f"MobilePerf on_log callback failed: {type(exc).__name__}", context,
                    )

    def _read_diagnostics(self, context: _MobilePerfRunContext) -> None:
        """持续排空子进程 stderr，源码模式转发到 IDE，打包模式直接丢弃。"""
        proc = context.proc
        stream = getattr(proc, "stderr", None)
        if stream is None:
            self._mark_reader_done(context, context.stderr_done)
            return
        try:
            for line in stream:
                text = str(line).rstrip("\r\n")
                if text:
                    self._safe_write_diagnostic(text, context)
        except Exception as exc:
            self._safe_write_diagnostic(
                f"MobilePerf stderr reader failed: {type(exc).__name__}",
                context,
            )
        finally:
            try:
                stream.close()
            except Exception:
                pass
            self._mark_reader_done(context, context.stderr_done)

    def _safe_write_diagnostic(
        self,
        message: str,
        context: _MobilePerfRunContext | None = None,
    ) -> None:
        """隔离诊断输出异常，避免写入失败终止管道 reader。"""
        try:
            if context is None:
                self._write_diagnostic(message)
            else:
                self._write_diagnostic(message, context.redaction_values)
        except Exception:
            pass

    def _write_diagnostic(
        self,
        message: str,
        redaction_values: tuple[str, ...] | None = None,
    ) -> None:
        """在源码模式把脱敏诊断写入 stderr，按控制台级别过滤可分级记录。"""
        if self._is_frozen():
            return
        stream = getattr(sys, "stderr", None)
        if stream is None:
            return
        if not callable(getattr(stream, "write", None)):
            return
        # 只在最终显示层识别固定协议级别；未带级别的原始行（异常栈续行）不过滤，
        # 避免设置阈值后只剩报错头而丢失上下文。
        level_match = self._DIAGNOSTIC_LEVEL_PATTERN.match(str(message))
        if level_match is not None and not should_emit(level_match.group(1)):
            return
        text = self._redact_runtime_values(
            str(message),
            redaction_values=redaction_values,
        )
        # 子进程管道和文件保留纯文本，颜色只加在控制台显示层。
        if level_match is not None:
            text = colorize_console(level_match.group(1), text, stream)
        try:
            with self._diagnostic_lock:
                stream.write(text + "\n")
                stream.flush()
        except Exception:
            pass

    def _sensitive_runtime_values(
        self,
        config: MobilePerfRunConfig,
        *,
        config_path: str | None = None,
        stop_path: str | None = None,
    ) -> list[str]:
        """返回本次运行禁止出现在诊断输出中的动态值。"""
        candidates = (
            config.device_id,
            config.package,
            config.mailbox,
            config.result_root,
            str(self._project_root),
            self._config_path if config_path is None else config_path,
            self._stop_path if stop_path is None else stop_path,
        )
        return sorted(
            {str(value) for value in candidates if str(value or "")},
            key=len,
            reverse=True,
        )

    def _redact_runtime_values(
        self,
        message: str,
        *,
        redaction_values: tuple[str, ...] | None = None,
    ) -> str:
        values = redaction_values
        if values is None:
            config = self._last_config
            if config is None:
                return message
            values = tuple(self._sensitive_runtime_values(config))
        redacted = message
        for value in values:
            redacted = redacted.replace(value, "<redacted>")
        return redacted

    def _mark_reader_done(
        self,
        context: _MobilePerfRunContext,
        reader_done: threading.Event,
    ) -> None:
        reader_done.set()
        self._maybe_notify_finished(context)

    def _maybe_notify_finished(self, context: _MobilePerfRunContext) -> None:
        """仅在同一运行的管道排空、模式写入结束且进程退出后发送完成通知。"""
        if (
            not context.stdout_done.is_set() or not context.stderr_done.is_set()
            or not context.mode_done.is_set()
        ):
            return
        with context.finish_lock:
            if context.finished_notified:
                return
            exit_code = context.exit_code
            deadline = time.monotonic() + self.PIPE_EXIT_POLL_SECONDS
            while exit_code is None:
                try:
                    exit_code = context.proc.poll()
                except Exception:
                    exit_code = None
                if exit_code is not None or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
                exit_code = context.exit_code
            if exit_code is None:
                return
            context.finished_notified = True
            context.exit_code = exit_code
        self._release_process_tracking(
            context,
            context.process_key,
            timeout=0,
        )
        if context.process_tracking_released:
            self._cleanup_run_context(context)
        else:
            with self._state_lock:
                self._residual_contexts.append(context)
        with self._state_lock:
            notify = self._active_context is context
            if notify:
                self._last_exit_code = exit_code
                self._proc = None
                self._active_context = None
        if notify and context.on_finished:
            try:
                context.on_finished()
            except Exception as exc:
                self._safe_write_diagnostic(
                    f"MobilePerf on_finished callback failed: {type(exc).__name__}",
                    context,
                )

    def _release_process_tracking(
        self,
        context: _MobilePerfRunContext | None,
        process_key: str,
        *,
        timeout: float,
    ) -> int | None:
        """按运行代次串行停止；只有确认退出后才标记跟踪已释放。"""
        if context is None:
            return self._process_runner.stop(process_key, timeout=timeout)
        with context.tracking_lock:
            if context.process_tracking_released:
                return context.exit_code
            code = self._process_runner.stop(process_key, timeout=timeout)
            if code is None:
                if isinstance(context.proc, OwnedWorkerProcess):
                    if context.proc.resources_released():
                        code = context.proc.poll()
                else:
                    code = context.proc.poll()
            if code is not None:
                context.exit_code = code
                context.process_tracking_released = True
            return code

    def _join_context_readers(
        self,
        context: _MobilePerfRunContext | None,
        *,
        timeout: float,
    ) -> None:
        if context is None:
            return
        deadline = time.monotonic() + max(0.0, float(timeout))
        for thread in (context.log_thread, context.diagnostic_thread, context.mode_thread):
            if thread is None or thread is threading.current_thread() or not thread.is_alive():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _join_stop_resources(
        self,
        context: _MobilePerfRunContext | None,
        mode_contexts: tuple[_MobilePerfRunContext, ...],
        *,
        timeout: float,
    ) -> None:
        """在同一预算内等待停止快照的管道及各代 writer，不碰随后启动的新运行。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        self._join_context_readers(context, timeout=max(0.0, deadline - time.monotonic()))
        for mode_context in mode_contexts:
            if mode_context is context:
                continue
            thread = mode_context.mode_thread
            if (
                thread is not None and thread is not threading.current_thread()
                and thread.is_alive()
            ):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _cleanup_run_context(self, context: _MobilePerfRunContext) -> None:
        context.mode_stop.set()
        if not context.mode_done.is_set():
            return
        with context.finish_lock:
            if context.config_cleaned:
                return
            context.config_cleaned = True
        try:
            context.config_dir.cleanup()
        except Exception:
            pass
        with self._state_lock:
            if self._config_dir is context.config_dir:
                self._config_dir = None
                self._stop_path = ""

    def _cleanup_config_dir(self):
        with self._state_lock:
            context = self._active_context
            config_dir = self._config_dir
        if context is not None and context.config_dir is config_dir:
            self._cleanup_run_context(context)
            return
        if config_dir is not None:
            config_dir.cleanup()
            with self._state_lock:
                if self._config_dir is config_dir:
                    self._config_dir = None
                    self._stop_path = ""

    def _capture_result_baseline(self, config: MobilePerfRunConfig) -> None:
        root = self._package_result_root(config)
        self._baseline_package_root = self._path_key(root)
        self._baseline_result_dirs = {}
        self._baseline_reports = {}
        if not root.exists():
            return
        for result_dir in root.iterdir():
            if not result_dir.is_dir():
                continue
            self._baseline_result_dirs[self._path_key(result_dir)] = self._path_signature(
                result_dir
            )
            for report in result_dir.glob("summary_*.xlsx"):
                self._baseline_reports[self._path_key(report)] = self._path_signature(report)

    def _result_baseline_for(
        self,
        root: Path,
    ) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
        if self._path_key(root) != self._baseline_package_root:
            return {}, {}
        return self._baseline_result_dirs, self._baseline_reports

    def _contains_current_report(
        self,
        result_dir: Path,
        baseline_reports: dict[str, tuple[int, int]],
    ) -> bool:
        return any(
            self._is_current_valid_report(report, baseline_reports)
            for report in result_dir.glob("summary_*.xlsx")
        )

    def _is_current_valid_report(
        self,
        report: Path,
        baseline_reports: dict[str, tuple[int, int]],
    ) -> bool:
        signature = self._path_signature(report)
        return signature[1] > 0 and signature != baseline_reports.get(self._path_key(report))

    def _package_result_root(self, config: MobilePerfRunConfig | None) -> Path:
        root = Path(self.expected_result_root(config))
        if config and config.package:
            primary = _primary_package(config.package)
            segment = _RESULT_SEGMENT_UNSAFE_RE.sub("_", primary).strip(".")
            if segment:
                root = root / segment
        return root

    @staticmethod
    def _path_key(path: Path) -> str:
        return path_key(path)

    @staticmethod
    def _path_signature(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except OSError:
            return (-1, -1)
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _resolve_adb_path() -> str:
        """主应用启动子进程必须冻结已选择的 ADB，不能让采集器自行换用环境客户端。"""
        from core.exec import require_adb_program

        return require_adb_program()

    def _build_command(self) -> list[str]:
        if self._is_frozen():
            return [
                self._python_executable,
                "--mobileperf-worker",
                "--config",
                self._config_path,
            ]
        return [
            self._python_executable,
            "-m",
            "mobileperf.android.startup",
            "--config",
            self._config_path,
        ]

    @staticmethod
    def _default_project_root() -> Path:
        if getattr(sys, "frozen", False):
            return Path(resource_path("."))
        # 源码 worker 通过 -m 导入 mobileperf，工作目录必须是包含该包的仓库根。
        return Path(__file__).resolve().parents[1]

    @staticmethod
    def _is_frozen() -> bool:
        return bool(getattr(sys, "frozen", False))
