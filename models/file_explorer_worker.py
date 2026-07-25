"""提供在 QThread 中执行 ADB Shell 和文件传输的后台任务。"""

import os
import subprocess

from PySide6.QtCore import QThread, Signal

from .base.command_runner import CommandRunner
from .base.process_runner import ProcessRunner


class ADBWorker(QThread):
    """执行短 ADB Shell 命令，并通过完成信号返回输出或错误。"""

    finished = Signal(str, bool)

    def __init__(self, device_ip: str, args: list, timeout: int = 30):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self.timeout = timeout
        self._aborted = False

    def abort(self):
        """设置中止意图，命令返回后不再发送完成结果。"""
        self._aborted = True
        self.requestInterruption()

    def run(self):
        """执行一次短命令，并将失败状态作为信号参数传播。"""
        result = CommandRunner.run(["adb", "-s", self.device_ip] + self.args, timeout=self.timeout)
        if self._aborted:
            return
        if result.success:
            self.finished.emit(result.output, False)
        else:
            self.finished.emit(result.error, True)


class TransferWorker(QThread):
    """执行 pull 或 push 长进程，并逐行发送进度。"""

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
        """请求中止并停止当前传输进程。"""
        self._aborted = True
        self.requestInterruption()
        self._process_runner.stop(self._process_key, timeout=2)

    def run(self):
        """启动传输进程；无论成功、失败或异常都取消进程注册。"""
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
