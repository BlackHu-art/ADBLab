"""Process adapter for the vendored mobileperf command-line collector."""

from __future__ import annotations

import configparser
import glob
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from models.base.process_runner import ProcessRunner


def _split_semicolon(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [item.strip() for item in value.split(";") if item.strip()]


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
    """Structured Monkey command options written into the temporary mobileperf config."""

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
    """User-facing mobileperf run configuration."""

    device_id: str = ""
    package: str = ""
    frequency_seconds: int = 5
    timeout_minutes: int = 10
    dumpheap_minutes: int = 60
    monkey_enabled: bool = False
    exception_keywords: list[str] = field(
        default_factory=lambda: ["fatal exception", "has died"]
    )
    phone_log_paths: list[str] = field(default_factory=lambda: ["/data/anr"])
    save_path: str = ""
    mailbox: str = ""
    monkey_config: MobilePerfMonkeyConfig = field(default_factory=MobilePerfMonkeyConfig)

    @property
    def result_root(self) -> str:
        return normalize_local_path(self.save_path)

    def to_config_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        common = {
            "package": self.package.strip(),
            "frequency": str(max(1, int(self.frequency_seconds))),
            "timeout": str(max(1, int(self.timeout_minutes))),
            "dumpheap_freq": str(max(1, int(self.dumpheap_minutes))),
            "serialnum": self.device_id.strip(),
            "exceptionlog": ";".join(_split_semicolon(self.exception_keywords)),
            "monkey": "true" if self.monkey_enabled else "false",
            "save_path": self.result_root,
            "phone_log_path": ";".join(_split_semicolon(self.phone_log_paths)),
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


class MobilePerfRunner:
    """Start and stop mobileperf in a subprocess isolated from the Qt app."""

    LOG_BATCH_SIZE = 50
    LOG_BATCH_INTERVAL_SECONDS = 0.2
    REPORT_SHUTDOWN_TIMEOUT_SECONDS = 90.0

    def __init__(
        self,
        *,
        process_runner: ProcessRunner | None = None,
        project_root: str | os.PathLike[str] | None = None,
        python_executable: str | None = None,
    ):
        self._process_runner = process_runner or ProcessRunner()
        self._project_root = Path(project_root or Path(__file__).resolve().parents[2])
        self._python_executable = python_executable or sys.executable
        self._process_key = f"mobileperf_{id(self)}"
        self._proc: subprocess.Popen | None = None
        self._config_dir: tempfile.TemporaryDirectory[str] | None = None
        self._config_path: str = ""
        self._stop_path: str = ""
        self._log_thread: threading.Thread | None = None
        self._on_log: Callable[[str], None] | None = None
        self._on_finished: Callable[[], None] | None = None
        self._finished_notified = False
        self._last_config: MobilePerfRunConfig | None = None

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def last_config(self) -> MobilePerfRunConfig | None:
        return self._last_config

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(
        self,
        config: MobilePerfRunConfig,
        *,
        on_log: Callable[[str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> str:
        if self.is_running():
            raise RuntimeError("mobileperf is already running")
        self._last_config = config
        self._on_log = on_log
        self._on_finished = on_finished
        self._finished_notified = False
        self._config_dir = tempfile.TemporaryDirectory(prefix="adblab_mobileperf_")
        self._config_path = config.write_config(self._config_dir.name)
        self._stop_path = os.path.join(self._config_dir.name, "mobileperf.stop")
        cmd = [
            self._python_executable,
            "-m",
            "mobileperf.android.startup",
            "--config",
            self._config_path,
        ]
        env = os.environ.copy()
        adb_path = self._resolve_adb_path()
        if adb_path:
            env["ADB_PATH"] = adb_path
        env["MOBILEPERF_STOP_FILE"] = self._stop_path
        try:
            self._proc = self._process_runner.start(
                self._process_key,
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(self._project_root),
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
                env=env,
            )
        except Exception:
            self._cleanup_config_dir()
            raise
        self._log_thread = threading.Thread(
            target=self._read_logs,
            name="adblab-mobileperf-log",
            daemon=True,
        )
        self._log_thread.start()
        return self.expected_result_root(config)

    def stop(self, timeout: float = REPORT_SHUTDOWN_TIMEOUT_SECONDS) -> int | None:
        proc = self._proc
        if proc is None:
            return None
        code: int | None
        if proc.poll() is None:
            self.request_stop()
            try:
                proc.wait(timeout=timeout)
                code = proc.returncode
                self._process_runner.stop(self._process_key, timeout=0)
            except subprocess.TimeoutExpired:
                code = self._process_runner.stop(self._process_key, timeout=3)
        else:
            code = proc.returncode
            self._process_runner.stop(self._process_key, timeout=0)
        self._proc = None
        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=1.0)
        self._log_thread = None
        self._on_log = None
        self._on_finished = None
        self._finished_notified = True
        self._cleanup_config_dir()
        return code

    def request_stop(self):
        if not self._stop_path:
            return
        Path(self._stop_path).write_text("stop", encoding="utf-8")

    def expected_result_root(self, config: MobilePerfRunConfig | None = None) -> str:
        cfg = config or self._last_config
        if cfg and cfg.result_root:
            return cfg.result_root
        return str(self._project_root / "results")

    def latest_result_dir(self, config: MobilePerfRunConfig | None = None) -> str:
        cfg = config or self._last_config
        root = Path(self.expected_result_root(cfg))
        if cfg and cfg.package:
            root = root / _primary_package(cfg.package)
        if not root.exists():
            return ""
        dirs = [path for path in root.iterdir() if path.is_dir()]
        if not dirs:
            return ""
        return str(max(dirs, key=lambda path: path.stat().st_mtime))

    def latest_report_file(self, config: MobilePerfRunConfig | None = None) -> str:
        result_dir = self.latest_result_dir(config)
        if not result_dir:
            return ""
        reports = glob.glob(os.path.join(result_dir, "summary_*.xlsx"))
        if not reports:
            return ""
        return max(reports, key=os.path.getmtime)

    def _read_logs(self):
        proc = self._proc
        if not proc or not proc.stdout:
            return
        pending: list[str] = []
        last_flush = time.monotonic()

        def flush_pending():
            nonlocal last_flush
            if pending and self._on_log:
                self._on_log("\n".join(pending))
            pending.clear()
            last_flush = time.monotonic()

        try:
            for line in proc.stdout:
                text = line.rstrip("\r\n")
                if not text:
                    continue
                pending.append(text)
                now = time.monotonic()
                if (
                    len(pending) >= self.LOG_BATCH_SIZE
                    or now - last_flush >= self.LOG_BATCH_INTERVAL_SECONDS
                ):
                    flush_pending()
            flush_pending()
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            if proc.poll() is not None:
                self._cleanup_config_dir()
                self._notify_finished()

    def _notify_finished(self):
        if self._finished_notified:
            return
        self._finished_notified = True
        if self._on_finished:
            self._on_finished()

    def _cleanup_config_dir(self):
        if self._config_dir is not None:
            self._config_dir.cleanup()
            self._config_dir = None
        self._stop_path = ""

    @staticmethod
    def _resolve_adb_path() -> str:
        try:
            from utils.adb_resolver import adb_path

            return adb_path()
        except Exception:
            return ""
