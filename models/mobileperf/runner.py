"""Process adapter for the vendored mobileperf command-line collector."""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from models.base.process_runner import ProcessRunner


def _split_semicolon(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [item.strip() for item in value.split(";") if item.strip()]


def normalize_local_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    return os.path.normpath(value)


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

    @property
    def result_root(self) -> str:
        return normalize_local_path(self.save_path)

    def to_config_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        parser["Common"] = {
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

    def stop(self, timeout: float = 5.0) -> int | None:
        code = self._process_runner.stop(self._process_key, timeout=timeout)
        self._proc = None
        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=0.5)
        self._log_thread = None
        self._on_log = None
        self._on_finished = None
        self._finished_notified = True
        self._cleanup_config_dir()
        return code

    def expected_result_root(self, config: MobilePerfRunConfig | None = None) -> str:
        cfg = config or self._last_config
        if cfg and cfg.result_root:
            return cfg.result_root
        return str(self._project_root / "results")

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

    @staticmethod
    def _resolve_adb_path() -> str:
        try:
            from utils.adb_resolver import adb_path

            return adb_path()
        except Exception:
            return ""
