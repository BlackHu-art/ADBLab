"""提供在 QThread 中执行 ADB Shell 和文件传输的后台任务。"""

import os
import subprocess
import threading
import time
import uuid

from PySide6.QtCore import QThread, Signal

from core.exec import CommandRunner, ProcessRunner
from core.log_service import LogService
from services import file_explorer as explorer_service
from services import file_operations
from services.file_download import SafeFileDownload


class ADBWorker(QThread):
    """执行短 ADB Shell 命令，并通过业务结果信号返回输出或错误。"""

    result_ready = Signal(str, bool)

    def __init__(self, device_ip: str, args: list, timeout: int = 30):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self.timeout = timeout
        self._aborted = threading.Event()

    def abort(self):
        """设置中止意图，命令返回后不再发送完成结果。"""
        self._aborted.set()
        self.requestInterruption()

    def run(self):
        """执行一次短命令，并将失败状态作为信号参数传播。"""
        if self._aborted.is_set() or self.isInterruptionRequested():
            return
        result = CommandRunner.run(
            ["adb", "-s", self.device_ip] + self.args, timeout=self.timeout,
            cancelled=self._aborted.is_set,
        )
        if self._aborted.is_set():
            return
        if result.success:
            self.result_ready.emit(result.output, False)
        else:
            self.result_ready.emit(result.error, True)


class DirectoryListWorker(ADBWorker):
    """目录名称绕过通用文本规范化，完成校验后才发布可操作快照。"""

    result_ready = Signal(object, bool)

    def __init__(self, device_ip: str, path: str, use_root: bool):
        super().__init__(device_ip, [], timeout=30)
        self.path = path
        self.use_root = use_root
        self._completion_marker = f"ADBLAB_LIST_END_{uuid.uuid4().hex}".encode("ascii")

    def run(self):
        """保留目录信号适配，事务负责原始字节校验和暂存清理。"""
        file_operations.read_directory(
            self.device_ip, self.path, self.use_root, self._completion_marker,
            timeout=self.timeout, capture=CommandRunner.run_to_file,
            cancelled=self._aborted.is_set, publish=self.result_ready.emit,
        )


class TextReadWorker(ADBWorker):
    """正文通过无 PTY 的原始字节通道读取，本地文件仅由后台任务拥有。"""

    result_ready = Signal(object, bool)
    decoded_ready = Signal(object)

    def __init__(self, device_ip: str, path: str, use_root: bool, byte_limit: int):
        self._completion_marker = f"ADBLAB_TEXT_END_{uuid.uuid4().hex}".encode("ascii")
        args = file_operations.text_read_arguments(
            path, use_root, byte_limit, self._completion_marker,
        )
        super().__init__(device_ip, args)
        self.byte_limit = byte_limit
        self.decoded_available = False

    def run(self):
        """沿构造期命令读取正文，同步信号的发布时点由事务保持。"""
        file_operations.read_text(
            self.device_ip, self.args, self.byte_limit, self._completion_marker,
            timeout=self.timeout, capture=CommandRunner.run_to_file,
            cancelled=self._aborted.is_set, decoded=self._publish_decoded,
            publish=self.result_ready.emit,
        )

    def _publish_decoded(self, preview: explorer_service.TextPreview) -> None:
        """先置兼容标志，再同步交付解码结果。"""
        self.decoded_available = True
        self.decoded_ready.emit(preview)


class TextSaveWorker(ADBWorker):
    """固定设备和正文快照，在后台上传并发布；清理独立于已取消的操作。"""

    def __init__(self, device_ip: str, path: str, content: bytes, use_root: bool):
        super().__init__(device_ip, [], timeout=120)
        self.path = path
        self.content = content
        self.use_root = use_root

    def run(self):
        """保存固定正文快照，事务清理收口后才发送原终态信号。"""
        file_operations.save_device_text(
            self.device_ip, self.path, self.content, self.use_root,
            timeout=self.timeout, run=CommandRunner.run, capture=CommandRunner.run_to_file,
            cancelled=self._aborted.is_set, publish=self.result_ready.emit,
            warning=self._warn_cleanup,
        )

    def _warn_cleanup(self, message: str) -> None:
        """仅在清理失败时创建日志适配，不向事务引入 Qt 依赖。"""
        LogService().log("WARNING", message)


class LocalTextSaveWorker(ADBWorker):
    """本地另存为同样在后台写临时文件，取消或失败不覆盖旧文件。"""

    def __init__(self, path: str, content: bytes):
        super().__init__("", [])
        self.path = path
        self.content = content

    def run(self):
        """保留后台线程归属，本地事务独占同目录暂存与替换。"""
        file_operations.save_local_text(
            self.path, self.content, cancelled=self._aborted.is_set,
            publish=self.result_ready.emit,
        )


class TransferWorker(QThread):
    """受控下载或 push 长进程，并分别发送进度和业务结果。"""

    progress = Signal(str)
    result_ready = Signal(str, bool, str)

    def __init__(self, device_ip: str, args: list, cwd: str = ""):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self.cwd = cwd or os.getcwd()
        self._proc = None
        self._process_key = f"transfer_{id(self)}"
        self._process_runner = ProcessRunner()
        self._aborted = threading.Event()
        self._run_entered = threading.Event()
        self._run_finished = threading.Event()

    def request_stop(self):
        """非阻塞记录取消意图，并唤醒被进程输出读取阻塞的线程。"""
        self._aborted.set()
        self.requestInterruption()
        self._process_runner.request_stop(self._process_key)

    def abort(self):
        """兼容页面旧取消入口，不在 GUI 线程等待进程退出。"""
        self.request_stop()

    def is_active(self) -> bool:
        """线程、执行体或实际进程任一未退出时保留监督记录。"""
        return (self.isRunning() or not self.wait(0)
                or (self._run_entered.is_set() and not self._run_finished.is_set())
                or (self._proc is not None and self._proc.poll() is None))

    def wait_stopped(self, timeout: float) -> bool:
        """只供后台监督器使用，等待线程并复核实际进程状态。"""
        self.wait(max(0, int(timeout * 1000)))
        return not self.is_active()

    def force_stop(self, timeout: float) -> bool:
        """后台强停保留原进程归属，不能以 kill 已发送推断退出。"""
        self.request_stop()
        deadline = time.monotonic() + max(0.0, timeout)
        self._process_runner.force_stop(self._process_key, timeout=timeout)
        return self.wait_stopped(max(0.0, deadline - time.monotonic()))

    def run(self):
        """启动后再次检查取消；仅在确认进程退出后注销资源。"""
        self._run_entered.set()
        try:
            if self._aborted.is_set() or self.isInterruptionRequested():
                return
            if self.args and self.args[0] == "pull":
                if len(self.args) != 3:
                    raise ValueError("Invalid download arguments")
                destination = os.path.join(self.cwd, self.args[2])
                SafeFileDownload(
                    self.device_ip, self._aborted.is_set, self.progress.emit,
                ).download(self.args[1], destination)
                if not self._aborted.is_set():
                    self.result_ready.emit("OK", False, self.args[2])
                return
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
            if self._aborted.is_set():
                self._process_runner.request_stop(self._process_key)
                return
            last = ""
            stdout = self._proc.stdout
            if stdout is None:
                self.result_ready.emit("Transfer process stdout unavailable", True, "")
                return
            while not self._aborted.is_set():
                line = stdout.readline()
                if not line:
                    if self._proc.poll() is not None:
                        break
                    # stdout 已到 EOF 而进程尚未退出：短暂等待避免空转忙等。
                    time.sleep(0.05)
                    continue
                last = line.rstrip("\n")
                self.progress.emit(last)
            if self._aborted.is_set():
                return
            ret = self._proc.wait()
            local = self.args[-1] if len(self.args) >= 2 else ""
            if ret == 0:
                self.result_ready.emit(last or "OK", False, local)
            else:
                self.result_ready.emit(last or f"Exit {ret}", True, local)
        except Exception as e:
            if not self._aborted.is_set():
                self.result_ready.emit(str(e), True, "")
        finally:
            if self._proc is not None and self._proc.poll() is not None:
                self._process_runner.stop(self._process_key, timeout=0)
            self._run_finished.set()
