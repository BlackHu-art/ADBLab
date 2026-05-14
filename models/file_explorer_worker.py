"""File Explorer background workers — QThread for ADB shell and file transfer."""

import os
import subprocess
import sys

from PySide6.QtCore import QThread, Signal


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
        try:
            cmd = ["adb", "-s", self.device_ip] + self.args
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            output = subprocess.check_output(
                cmd, text=True, stderr=subprocess.STDOUT, creationflags=cf, timeout=30,
            )
            if not self._aborted:
                self.finished.emit(output, False)
        except subprocess.CalledProcessError as e:
            if not self._aborted:
                self.finished.emit(e.output or str(e), True)
        except Exception as e:
            if not self._aborted:
                self.finished.emit(str(e), True)


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
        self._aborted = False

    def abort(self):
        self._aborted = True
        self.requestInterruption()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        try:
            cmd = ["adb", "-s", self.device_ip] + self.args
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=self.cwd, universal_newlines=True, bufsize=1, creationflags=cf,
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
