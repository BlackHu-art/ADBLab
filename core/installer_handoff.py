"""主进程持有的升级交接会话；准备可以失败，提交只能发生在根入口清理后。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from threading import Event, Lock

from core.installer_update_process import ParentProcess, locked_file, read_pipe_line
from core.installer_update_protocol import HELPER_NAME, child_environment, validate_request
from services.installer_update import VerifiedInstaller, verify_download
from utils.resource_path import resource_path


class InstallerHandoff:
    """仅组合根可提供的安装能力；普通窗口关闭不会自行创建升级授权。"""

    def __init__(self):
        self._lock = Lock()
        self._cancel = Event()
        self._process: subprocess.Popen | None = None
        self._prepared = False
        self._approved = False
        self._committed = False
        self._nonce = ""
        self._preparing = False

    @property
    def prepared(self) -> bool:
        return self._prepared and not self._cancel.is_set()

    def _helper_source(self) -> tuple[Path, str]:
        """读取启动准入所核验清单里的 helper 摘要，防止复制被修改的运行时。"""
        from core.windows_installation import INSTALL_MANIFEST

        source = Path(resource_path(f"runtime-helpers/{HELPER_NAME}/{HELPER_NAME}.exe"))
        root = Path(sys.executable).absolute().parent
        relative = source.relative_to(root).as_posix()
        lines = (root / INSTALL_MANIFEST).read_text(encoding="utf-8-sig").splitlines()
        matches = [line.split("\t")[0] for line in lines
                   if line.endswith("\t" + relative)]
        if len(matches) != 1 or len(matches[0]) != 64:
            raise ValueError("handoff helper missing from installation manifest")
        return source, matches[0]

    def prepare(self, verified: VerifiedInstaller) -> None:
        """后台复制并握手；未 READY 不开始关闭，失败可在当前窗口重试。"""
        with self._lock:
            if self._preparing or self._cancel.is_set():
                raise RuntimeError("handoff attempt unavailable")
            self._preparing = True
        try:
            self._prepare(verified)
        finally:
            with self._lock:
                self._preparing = False

    def reset_attempt(self) -> None:
        """只在上次工作线程结束后显式重试；旧 helper 未退出时拒绝重置。"""
        with self._lock:
            if self._preparing or (self._process is not None and self._process.poll() is None):
                raise RuntimeError("previous handoff is still active")
            if self._process is not None and self._process.stdout is not None:
                self._process.stdout.close()
            self._process = None
            self._cancel = Event()
            self._approved = self._prepared = False
            self._committed = False
            self._nonce = ""

    def _prepare(self, verified: VerifiedInstaller) -> None:
        """准备步骤由 prepare 串行执行，取消信号在整次尝试中保持同一身份。"""
        if self._cancel.is_set():
            raise InterruptedError("handoff cancelled")
        if self._process is not None:
            raise RuntimeError("handoff already prepared")
        verified = verify_download(verified.path, verified.asset, cancelled=self._cancel.is_set)
        with ParentProcess(os.getpid()) as parent:
            nonce = secrets.token_hex(16)
            request = {"protocol": 1, "pid": os.getpid(), "created": parent.created,
                       "nonce": nonce, "path": str(verified.path), "asset": asdict(verified.asset)}
        validate_request(request)
        source, expected = self._helper_source()
        target = verified.path.parent / f"{HELPER_NAME}-{nonce}.exe"
        try:
            with locked_file(source) as stream, target.open("xb") as output:
                digest = hashlib.sha256()
                while chunk := stream.read(64 * 1024):
                    if self._cancel.is_set():
                        raise InterruptedError("handoff cancelled")
                    output.write(chunk)
                    digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError("handoff helper digest mismatch")
                output.flush()
                os.fsync(output.fileno())
            with locked_file(target) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError("copied helper changed")
                process = subprocess.Popen([str(target)], cwd=target.parent,
                                           env=child_environment(), stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW,
                                           close_fds=True)
            with self._lock:
                self._process, self._nonce = process, nonce
                if self._cancel.is_set():
                    raise InterruptedError("handoff cancelled")
                assert process.stdin is not None
                process.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
                process.stdin.flush()
            assert process.stdout is not None
            answer = read_pipe_line(process.stdout, timeout=45, cancel=self._cancel)
            if answer != f"READY {nonce}".encode("ascii"):
                raise ValueError("invalid helper handshake")
            with self._lock:
                if self._cancel.is_set() or process.poll() is not None:
                    raise InterruptedError("handoff unavailable")
                self._prepared = True
        except BaseException:
            self._close_channel()
            # 只等待自己的未授权 helper 看到 EOF；不杀进程、不删除可能仍被加载的文件。
            if self._process is not None:
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                if self._process.poll() is not None:
                    if self._process.stdout is not None:
                        self._process.stdout.close()
                    self._process = None
            raise

    def has_pending_helper(self) -> bool:
        """只观察失败或撤销后仍活跃的 helper；READY 交接需跨父进程退出保留。"""
        with self._lock:
            return (not self._prepared and not self._committed and self._process is not None
                    and self._process.poll() is None)

    def wait_pending_helper(self, timeout: float) -> bool:
        """后台有界等待未授权 helper；超时保留归属，不终止进程或等待 READY 交接。"""
        with self._lock:
            process = None if self._prepared or self._committed else self._process
        if process is None:
            return True
        if process.poll() is None:
            if timeout <= 0:
                return False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return False
        with self._lock:
            if self._process is process:
                if process.stdout is not None:
                    process.stdout.close()
                self._process = None
        return True

    def mark_shutdown_success(self, succeeded: bool) -> None:
        """关闭 owner 只记录严格屏障结果，不能在此启动安装器。"""
        self._approved = bool(succeeded) and self.prepared

    def _close_channel(self) -> None:
        with self._lock:
            self._prepared = False
            if self._process is not None and self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except OSError:
                    # 对端已退出等同撤销；没有 COMMIT 就不能运行安装器。
                    pass
                self._process.stdin = None

    def abort(self) -> None:
        """撤销本会话并关闭管道，helper 自行退出，不同步等待 GUI。"""
        self._cancel.set()
        self._approved = False
        self._close_channel()

    def commit(self) -> None:
        """根入口成功释放安装锁之后调用；提交一次后无论结果均关闭管道。"""
        try:
            with self._lock:
                if self._approved and self.prepared and self._process is not None:
                    if self._process.poll() is None and self._process.stdin is not None:
                        self._process.stdin.write(f"COMMIT {self._nonce}\n".encode("ascii"))
                        self._process.stdin.flush()
                        self._committed = True
        except OSError:
            # 根入口已完成关闭；通道失败不能伪造升级完成或再启动另一个 helper。
            self._approved = False
        finally:
            self._close_channel()
