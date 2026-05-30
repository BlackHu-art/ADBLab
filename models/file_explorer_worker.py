"""File Explorer background workers — QThread for ADB shell and file transfer."""

import os
import subprocess

from PySide6.QtCore import QThread, Signal

from .base.command_runner import CommandRunner
from .base.process_runner import ProcessRunner


class ADBWorker(QThread):
    """Run a simple adb shell command and return output."""

    finished = Signal(str, bool)

    def __init__(self, device_ip: str, args: list):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self._aborted = False

    def abort(self):
        self._aborted = True
        self.requestInterruption()

    def run(self):
        result = CommandRunner.run(["adb", "-s", self.device_ip] + self.args, timeout=30)
        if self._aborted:
            return
        if result.success:
            self.finished.emit(result.output, False)
        else:
            self.finished.emit(result.error, True)


class TransferWorker(QThread):
    """Run pull/push operations with progress lines."""

    progress = Signal(str)
    finished = Signal(str, bool, str)

    def __init__(self, device_ip: str, args: list, cwd: str = ""):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self.cwd = cwd or os.getcwd()
        self._proc = None
        self._process_key = f"transfer_{id(self)}"
        self._process_runner = ProcessRunner()
        self._aborted = False

    def abort(self):
        self._aborted = True
        self.requestInterruption()
        self._process_runner.stop(self._process_key, timeout=2)

    def run(self):
        try:
            cmd = ["adb", "-s", self.device_ip] + self.args
            self._proc = self._process_runner.start(
                self._process_key,
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cwd,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
            )
            last = ""
            while not self._aborted:
                line = self._proc.stdout.readline()
                if not line and self._proc.poll() is not None:
                    break
                if line:
                    last = line.rstrip("\n")
                    self.progress.emit(last)
            if self._aborted:
                return
            ret = self._proc.wait()
            local = self.args[-1] if len(self.args) >= 2 else ""
            if ret == 0:
                self.finished.emit(last or "OK", False, local)
            else:
                self.finished.emit(last or f"Exit {ret}", True, local)
        except Exception as e:
            self.finished.emit(str(e), True, "")
        finally:
            self._process_runner.stop(self._process_key, timeout=0)
