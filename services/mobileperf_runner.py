"""在 Qt 主进程与内置 MobilePerf 命令行采集器之间提供进程隔离适配。"""

from __future__ import annotations

import configparser
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
from dataclasses import dataclass, field
from pathlib import Path

from models.base.process_runner import ProcessRunner
from utils.resource_path import resource_path
from utils.user_data import user_data_root


def _split_semicolon(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [item.strip() for item in value.split(";") if item.strip()]


def _normalize_package(value: str) -> str:
    """规范化分号分隔的包名，并保留原有顺序、大小写和重复项。"""
    return ";".join(_split_semicolon(value))


def _primary_package(value: str) -> str:
    parts = _split_semicolon(value)
    return parts[0] if parts else value.strip()


def normalize_local_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    return os.path.normpath(value)


@dataclass(slots=True)
class MobilePerfMonkeyConfig:
    """写入 MobilePerf 临时配置的结构化 Monkey 命令选项。"""

    throttle_ms: int = 500
    seed: int = 1000000
    ignore_crashes: bool = True
    ignore_timeouts: bool = True
    ignore_security: bool = True
    kill_after_error: bool = True
    pct_touch: int = 15
    pct_motion: int = 5
    pct_trackball: int = 0
    pct_nav: int = 40
    pct_majornav: int = 30
    pct_syskeys: int = 5
    pct_appswitch: int = 0
    pct_anyevent: int = 5
    pct_flip: int = 0
    pct_pinchzoom: int = 0

    @property
    def total_percentage(self) -> int:
        return sum(
            self._clamped_percent(value)
            for value in (
                self.pct_touch,
                self.pct_motion,
                self.pct_trackball,
                self.pct_nav,
                self.pct_majornav,
                self.pct_syskeys,
                self.pct_appswitch,
                self.pct_anyevent,
                self.pct_flip,
                self.pct_pinchzoom,
            )
        )

    def to_config_values(self) -> dict[str, str]:
        return {
            "monkey_throttle": str(max(1, int(self.throttle_ms))),
            "monkey_seed": str(max(0, int(self.seed))),
            "monkey_ignore_crashes": self._bool_text(self.ignore_crashes),
            "monkey_ignore_timeouts": self._bool_text(self.ignore_timeouts),
            "monkey_ignore_security": self._bool_text(self.ignore_security),
            "monkey_kill_after_error": self._bool_text(self.kill_after_error),
            "monkey_pct_touch": str(self._clamped_percent(self.pct_touch)),
            "monkey_pct_motion": str(self._clamped_percent(self.pct_motion)),
            "monkey_pct_trackball": str(self._clamped_percent(self.pct_trackball)),
            "monkey_pct_nav": str(self._clamped_percent(self.pct_nav)),
            "monkey_pct_majornav": str(self._clamped_percent(self.pct_majornav)),
            "monkey_pct_syskeys": str(self._clamped_percent(self.pct_syskeys)),
            "monkey_pct_appswitch": str(self._clamped_percent(self.pct_appswitch)),
            "monkey_pct_anyevent": str(self._clamped_percent(self.pct_anyevent)),
            "monkey_pct_flip": str(self._clamped_percent(self.pct_flip)),
            "monkey_pct_pinchzoom": str(self._clamped_percent(self.pct_pinchzoom)),
        }

    @staticmethod
    def _bool_text(value: bool) -> str:
        return "true" if bool(value) else "false"

    @staticmethod
    def _clamped_percent(value: int) -> int:
        return max(0, min(100, int(value)))


@dataclass(slots=True)
class MobilePerfRunConfig:
    """承载界面提交的 MobilePerf 单次运行配置。"""

    device_id: str = ""
    package: str = ""
    frequency_seconds: int = 5
    timeout_minutes: int = 10
    dumpheap_minutes: int = 60
    monkey_enabled: bool = False
    exception_keywords: list[str] = field(default_factory=lambda: ["fatal exception", "has died"])
    phone_log_paths: list[str] = field(default_factory=lambda: ["/data/anr"])
    save_path: str = ""
    mailbox: str = ""
    monkey_config: MobilePerfMonkeyConfig = field(default_factory=MobilePerfMonkeyConfig)

    def __post_init__(self) -> None:
        """在模型边界固化分号字段，避免后续序列化产生空项和多余空白。"""
        self.package = _normalize_package(self.package)
        self.exception_keywords = _split_semicolon(self.exception_keywords)
        self.phone_log_paths = _split_semicolon(self.phone_log_paths)

    @property
    def result_root(self) -> str:
        return normalize_local_path(self.save_path)

    def to_config_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        common = {
            "package": self.package,
            "frequency": str(max(1, int(self.frequency_seconds))),
            "timeout": str(max(1, int(self.timeout_minutes))),
            "dumpheap_freq": str(max(1, int(self.dumpheap_minutes))),
            "serialnum": self.device_id.strip(),
            "exceptionlog": ";".join(self.exception_keywords),
            "monkey": "true" if self.monkey_enabled else "false",
            "save_path": self.result_root,
            "phone_log_path": ";".join(self.phone_log_paths),
            "mailbox": self.mailbox.strip(),
            "pid_change_focus_package": "",
            "main_activity": "",
            "activity_list": "",
        }
        common.update(self.monkey_config.to_config_values())
        parser["Common"] = common
        return parser

    def write_config(self, directory: str | os.PathLike[str]) -> str:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "mobileperf_run.conf")
        parser = self.to_config_parser()
        with open(path, "w", encoding="utf-8") as fh:
            parser.write(fh)
        return path


@dataclass(slots=True)
class _MobilePerfRunContext:
    """保存单次 MobilePerf 运行中不得跨代复用的进程和回调状态。"""

    generation: int
    process_key: str
    proc: subprocess.Popen
    config: MobilePerfRunConfig
    redaction_values: tuple[str, ...]
    on_log: Callable[[str], None] | None
    on_finished: Callable[[], None] | None
    config_dir: tempfile.TemporaryDirectory[str]
    config_path: str
    stop_path: str
    stdout_done: threading.Event = field(default_factory=threading.Event)
    stderr_done: threading.Event = field(default_factory=threading.Event)
    finish_lock: threading.Lock = field(default_factory=threading.Lock)
    tracking_lock: threading.Lock = field(default_factory=threading.Lock)
    log_thread: threading.Thread | None = None
    diagnostic_thread: threading.Thread | None = None
    exit_code: int | None = None
    finished_notified: bool = False
    config_cleaned: bool = False
    process_tracking_released: bool = False


class MobilePerfRunner:
    """在与 Qt 应用隔离的子进程中启动、停止并跟踪 MobilePerf。"""

    LOG_BATCH_SIZE = 50
    LOG_BATCH_INTERVAL_SECONDS = 0.2
    PIPE_EXIT_POLL_SECONDS = 1.0
    REPORT_SHUTDOWN_TIMEOUT_SECONDS = 90.0
    _DEBUG_RECORD_PATTERN = re.compile(r"^\[[^\]]+\]DEBUG:mobileperf:")

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
        self._proc: subprocess.Popen | None = None
        self._config_dir: tempfile.TemporaryDirectory[str] | None = None
        self._config_path: str = ""
        self._stop_path: str = ""
        self._log_thread: threading.Thread | None = None
        self._diagnostic_thread: threading.Thread | None = None
        self._diagnostic_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._generation = 0
        self._active_context: _MobilePerfRunContext | None = None
        self._on_log: Callable[[str], None] | None = None
        self._on_finished: Callable[[], None] | None = None
        self._finished_notified = False
        self._last_config: MobilePerfRunConfig | None = None
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
        return self._proc is not None and self._proc.poll() is None

    def start(
        self,
        config: MobilePerfRunConfig,
        *,
        on_log: Callable[[str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> str:
        """创建临时配置并启动子进程，同时分别消费业务输出和开发诊断。"""
        with self._state_lock:
            if self.is_running():
                raise RuntimeError("mobileperf is already running")
            self._generation += 1
            generation = self._generation
            process_key = f"{self._process_key_prefix}_{generation}"
            self._process_key = process_key
            self._last_config = config
            self._last_exit_code = None
            self._capture_result_baseline(config)
            self._on_log = on_log
            self._on_finished = on_finished
            self._finished_notified = False
            config_dir = tempfile.TemporaryDirectory(prefix="adblab_mobileperf_")
            self._config_dir = config_dir
            self._config_path = config.write_config(config_dir.name)
            self._stop_path = os.path.join(config_dir.name, "mobileperf.stop")
            cmd = self._build_command()
            env = os.environ.copy()
            adb_path = self._resolve_adb_path()
            if adb_path:
                env["ADB_PATH"] = adb_path
            env["MOBILEPERF_STOP_FILE"] = self._stop_path
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
            try:
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
                )
            except Exception:
                config_dir.cleanup()
                self._config_dir = None
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
            )
            self._active_context = context
            self._proc = proc
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
            self._log_thread = context.log_thread
            self._diagnostic_thread = context.diagnostic_thread
            context.log_thread.start()
            if context.diagnostic_thread is not None:
                context.diagnostic_thread.start()
        self._safe_write_diagnostic(
            f"MobilePerf worker started: diagnostic_reader={diagnostic_stream is not None}",
            context,
        )
        return self.expected_result_root(config)

    def stop(self, timeout: float = REPORT_SHUTDOWN_TIMEOUT_SECONDS) -> int | None:
        """请求生成报告并等待退出，超过报告时限后强制停止进程。"""
        with self._state_lock:
            context = self._active_context
            proc = context.proc if context is not None else self._proc
            process_key = context.process_key if context is not None else self._process_key
        if proc is None:
            return None
        code: int | None
        if proc.poll() is None:
            self._request_stop_context(context)
            try:
                proc.wait(timeout=timeout)
                code = proc.returncode
                self._release_process_tracking(context, process_key, timeout=0)
            except subprocess.TimeoutExpired:
                code = self._release_process_tracking(context, process_key, timeout=3)
        else:
            code = proc.returncode
            self._release_process_tracking(context, process_key, timeout=0)
        if context is not None:
            context.exit_code = code
        with self._state_lock:
            if context is None or self._active_context is context:
                self._last_exit_code = code
                self._proc = None
        self._join_context_readers(context, timeout=1.0)
        if context is not None:
            self._maybe_notify_finished(context)
        with self._state_lock:
            if context is None or self._active_context is context:
                self._log_thread = None
                self._diagnostic_thread = None
                self._on_log = None
                self._on_finished = None
                self._finished_notified = bool(context is not None and context.finished_notified)
        if context is None:
            self._cleanup_config_dir()
        self._safe_write_diagnostic(
            f"MobilePerf worker stopped: exit_code={code}",
            context,
        )
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

    def expected_result_root(self, config: MobilePerfRunConfig | None = None) -> str:
        cfg = config or self._last_config
        if cfg and cfg.result_root:
            return cfg.result_root
        return str(self._project_root / "results")

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

    def latest_report_file(self, config: MobilePerfRunConfig | None = None) -> str:
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

    def _read_logs(self, context: _MobilePerfRunContext | None = None):
        """排空所属运行的 stdout，并按批次转发业务输出。"""
        proc = context.proc if context is not None else self._proc
        stream = getattr(proc, "stdout", None) if proc is not None else None
        if stream is None:
            if context is not None:
                self._mark_reader_done(context, context.stdout_done)
            return
        on_log = context.on_log if context is not None else self._on_log
        pending: list[str] = []
        last_flush = time.monotonic()

        def flush_pending():
            nonlocal last_flush
            payload = "\n".join(pending)
            pending.clear()
            last_flush = time.monotonic()
            if payload and on_log:
                try:
                    on_log(payload)
                except Exception as exc:
                    self._safe_write_diagnostic(
                        f"MobilePerf on_log callback failed: {type(exc).__name__}",
                        context,
                    )

        try:
            for line in stream:
                text = line.rstrip("\r\n")
                if not text:
                    continue
                # 子进程协议约定 DEBUG 使用 stderr；此处额外拦截误写 stdout 的诊断记录。
                if self._DEBUG_RECORD_PATTERN.match(text):
                    self._safe_write_diagnostic(text, context)
                    continue
                pending.append(text)
                now = time.monotonic()
                if (
                    len(pending) >= self.LOG_BATCH_SIZE
                    or now - last_flush >= self.LOG_BATCH_INTERVAL_SECONDS
                ):
                    flush_pending()
            flush_pending()
        except Exception as exc:
            self._safe_write_diagnostic(
                f"MobilePerf stdout reader failed: {type(exc).__name__}",
                context,
            )
        finally:
            try:
                stream.close()
            except Exception:
                pass
            if context is not None:
                self._mark_reader_done(context, context.stdout_done)
            elif proc is not None:
                exit_code = proc.poll()
                if exit_code is not None:
                    self._last_exit_code = exit_code
                    self._cleanup_config_dir()
                    self._notify_finished()

    def _read_diagnostics(self, context: _MobilePerfRunContext | None = None) -> None:
        """持续排空子进程 stderr，源码模式转发到 IDE，打包模式直接丢弃。"""
        proc = context.proc if context is not None else self._proc
        stream = getattr(proc, "stderr", None) if proc is not None else None
        if stream is None:
            if context is not None:
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
            if context is not None:
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
        """仅在源码模式把脱敏诊断信息写入当前进程 stderr。"""
        if self._is_frozen():
            return
        stream = getattr(sys, "stderr", None)
        if stream is None:
            return
        if not callable(getattr(stream, "write", None)):
            return
        text = self._redact_runtime_values(
            str(message),
            redaction_values=redaction_values,
        )
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
        """仅在同一运行的两个管道均排空且进程结束后发送完成通知。"""
        if not context.stdout_done.is_set() or not context.stderr_done.is_set():
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
        self._cleanup_run_context(context)
        with self._state_lock:
            if self._active_context is context:
                self._last_exit_code = exit_code
                self._proc = None
                self._active_context = None
                self._log_thread = None
                self._diagnostic_thread = None
                self._on_log = None
                self._on_finished = None
                self._finished_notified = True
        if context.on_finished:
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
        """按运行代次解除进程跟踪，避免旧停止流程命中新进程。"""
        if context is None:
            return self._process_runner.stop(process_key, timeout=timeout)
        with context.tracking_lock:
            if context.process_tracking_released:
                return context.exit_code
            context.process_tracking_released = True
        try:
            return self._process_runner.stop(process_key, timeout=timeout)
        except Exception:
            with context.tracking_lock:
                context.process_tracking_released = False
            raise

    def _join_context_readers(
        self,
        context: _MobilePerfRunContext | None,
        *,
        timeout: float,
    ) -> None:
        if context is None:
            return
        deadline = time.monotonic() + max(0.0, float(timeout))
        for thread in (context.log_thread, context.diagnostic_thread):
            if thread is None or thread is threading.current_thread() or not thread.is_alive():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _notify_finished(self):
        """保留旧测试和直接调用方使用的无上下文完成通知。"""
        if self._finished_notified:
            return
        self._finished_notified = True
        if self._on_finished:
            try:
                self._on_finished()
            except Exception as exc:
                self._safe_write_diagnostic(
                    f"MobilePerf on_finished callback failed: {type(exc).__name__}"
                )

    def _cleanup_run_context(self, context: _MobilePerfRunContext) -> None:
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
            root = root / _primary_package(config.package)
        return root

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(os.path.abspath(str(path)))

    @staticmethod
    def _path_signature(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except OSError:
            return (-1, -1)
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _resolve_adb_path() -> str:
        try:
            from utils.adb_resolver import adb_path

            return adb_path()
        except Exception:
            return ""

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
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _is_frozen() -> bool:
        return bool(getattr(sys, "frozen", False))
