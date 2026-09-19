"""提供在 QThread 中执行 ADB Shell 和文件传输的后台任务。"""

import os
import posixpath
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.exec import CommandRunner, ProcessRunner
from core.log_service import LogService
from services import file_explorer as explorer_service


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


class TextReadWorker(ADBWorker):
    """正文通过无 PTY 的原始字节通道读取，本地文件仅由后台任务拥有。"""

    result_ready = Signal(object, bool)

    def __init__(self, device_ip: str, path: str, use_root: bool, byte_limit: int):
        self._completion_marker = f"ADBLAB_TEXT_END_{uuid.uuid4().hex}".encode("ascii")
        command = explorer_service.root_command(
            explorer_service.head_command(path, byte_limit + 1)
            + f" && printf %s {explorer_service.shell_quote(self._completion_marker.decode())}",
            use_root,
        )
        super().__init__(device_ip, ["shell", "-T", command])
        self.byte_limit = byte_limit

    def run(self):
        """在成功、失败与取消路径都关闭并删除原始字节暂存文件。"""
        if self._aborted.is_set():
            return
        try:
            with tempfile.TemporaryDirectory(prefix="adblab-text-read-") as temporary:
                path = Path(temporary) / "content"
                result = CommandRunner.run_to_file(
                    ["adb", "-s", self.device_ip] + self.args, str(path),
                    timeout=self.timeout, cancelled=self._aborted.is_set,
                )
                if self._aborted.is_set():
                    return
                if result.success:
                    with path.open("rb") as stream:
                        raw = stream.read(self.byte_limit + 1 + len(self._completion_marker))
                    # 旧设备可能不传递远端退出码，完成标记防止把命令错误当成可编辑正文。
                    if not raw.endswith(self._completion_marker):
                        raise OSError("Unable to read complete text preview")
                    raw = raw[:-len(self._completion_marker)]
                    self.result_ready.emit(raw, False)
                else:
                    self.result_ready.emit(result.error, True)
        except OSError as exc:
            if not self._aborted.is_set():
                self.result_ready.emit(str(exc), True)


class TextSaveWorker(ADBWorker):
    """固定设备和正文快照，在后台上传并发布；清理独立于已取消的操作。"""

    def __init__(self, device_ip: str, path: str, content: bytes, use_root: bool):
        super().__init__(device_ip, [], timeout=120)
        self.path = path
        self.content = content
        self.use_root = use_root

    def _shell(self, command: str, *, root: bool, cleanup: bool = False):
        return CommandRunner.run(
            ["adb", "-s", self.device_ip, "shell", explorer_service.root_command(command, root)],
            timeout=15 if cleanup else 30,
            cancelled=None if cleanup else self._aborted.is_set,
        )

    def run(self):
        """上传正文不进入 argv；发布前任一步失败保留原文件，终态晚于清理。"""
        if self._aborted.is_set():
            return
        owned: list[tuple[str, bool]] = []
        error = ""
        try:
            resolved = self._shell(
                explorer_service.resolve_text_target_command(self.path), root=self.use_root,
            )
            if not resolved.success:
                raise OSError(resolved.error or "Unable to resolve writable text file")
            if (not resolved.output.startswith("ADBLAB_TARGET:")
                    or not resolved.output.endswith(":END")):
                raise OSError("Unable to resolve writable text file")
            target = resolved.output[len("ADBLAB_TARGET:"):-len(":END")]
            if not target.startswith("/") or any(char in target for char in "\0\r\n"):
                raise OSError("Invalid text file target")
            token = uuid.uuid4().hex
            directory = posixpath.join(posixpath.dirname(target), f".adblab-save-{token}")
            upload_directory = (
                f"/data/local/tmp/adblab-save-{token}" if self.use_root else directory
            )
            for remote, root in [(directory, self.use_root)] + (
                [(upload_directory, False)] if self.use_root else []
            ):
                if self._aborted.is_set():
                    return
                # 即使命令返回在取消时丢失，归属标记仍允许收口本次已创建的目录。
                owned.append((remote, root))
                result = self._shell(
                    explorer_service.prepare_text_directory_command(remote), root=root,
                )
                if not result.success:
                    raise OSError(result.error or "Unable to prepare text save")
            with tempfile.TemporaryDirectory(prefix="adblab-text-save-") as temporary:
                local = Path(temporary) / "content"
                local.write_bytes(self.content)
                if self._aborted.is_set():
                    return
                uploaded = f"{upload_directory}/upload"
                pushed = CommandRunner.run(
                    ["adb", "-s", self.device_ip, "push", str(local), uploaded],
                    timeout=self.timeout, cancelled=self._aborted.is_set,
                )
                if not pushed.success:
                    raise OSError(pushed.error or "Unable to upload text")
                if self._aborted.is_set():
                    return
                published = self._shell(
                    explorer_service.publish_text_command(target, directory, uploaded),
                    root=self.use_root,
                )
                if not published.success:
                    raise OSError(published.error or "Unable to publish text")
        except OSError as exc:
            error = str(exc)
        finally:
            for remote, root in reversed(owned):
                result = self._shell(
                    explorer_service.cleanup_text_directory_command(remote),
                    root=root, cleanup=True,
                )
                if not result.success:
                    error = error or "Text save temporary cleanup failed"
                    LogService().log("WARNING", "文本保存临时文件清理失败，请检查设备连接。")
            if not self._aborted.is_set():
                self.result_ready.emit(error or "OK", bool(error))


class LocalTextSaveWorker(ADBWorker):
    """本地另存为同样在后台写临时文件，取消或失败不覆盖旧文件。"""

    def __init__(self, path: str, content: bytes):
        super().__init__("", [])
        self.path = path
        self.content = content

    def run(self):
        """临时文件始终位于目标目录，发布后才发送成功。"""
        if self._aborted.is_set():
            return
        temporary = ""
        error = ""
        try:
            fd, temporary = tempfile.mkstemp(
                prefix=".adblab-save-", dir=str(Path(self.path).parent),
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(self.content)
            if self._aborted.is_set():
                return
            os.replace(temporary, self.path)
        except OSError as exc:
            error = str(exc)
        finally:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError as exc:
                    error = error or str(exc)
            if not self._aborted.is_set():
                self.result_ready.emit(error or "OK", bool(error))


class TransferWorker(QThread):
    """执行 pull 或 push 长进程，并分别发送进度和业务结果。"""

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
