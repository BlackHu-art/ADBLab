"""MobilePerf 显式客户端归属；登记只保存在本次 worker 的临时目录。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

import psutil

SCOPE_ENV = "ADBLAB_OWNED_CLIENT_DIR"


def _identity(pid: int) -> list[int | float]:
    return [pid, psutil.Process(pid).create_time()]


def _alive(identity) -> bool:
    """PID 重用表示旧身份已退出；权限或身份损坏必须向上报告未知状态。"""
    pid, birth = identity
    if not isinstance(pid, int) or pid <= 0 or not isinstance(birth, (int, float)):
        raise ValueError("无效的客户端身份")
    try:
        process = psutil.Process(pid)
        return process.create_time() == birth and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _write_record(directory: Path, record: dict) -> None:
    """原子发布登记；Windows 短暂读句柄会拒绝替换，只对此共享冲突有界重试。"""
    temporary = directory / "record.tmp"
    temporary.write_text(json.dumps(record), encoding="utf-8")
    deadline = time.monotonic() + 0.5
    while True:
        try:
            temporary.replace(directory / "record.json")
            return
        except PermissionError as error:
            if (
                sys.platform != "win32" or getattr(error, "winerror", None) not in (5, 32, 33)
                or time.monotonic() >= deadline
            ):
                raise
            # 父进程只短暂读取快照；不吞掉持续拒绝，也不改写旧记录或伪造 done。
            time.sleep(0.01)


class OwnedClientProcess(subprocess.Popen):
    """轻量 helper 只拥有直接客户端；停止文件与属主身份共同封闭启动竞态。"""

    def __init__(self, command: list[str], directory: str, **kwargs):
        self._confirmed_exit = False
        self._directory = Path(directory) / uuid.uuid4().hex
        self._directory.mkdir()
        owner = _identity(os.getpid())
        _write_record(self._directory, {"owner": owner, "phase": "starting"})
        prefix = ([sys.executable, "--adblab-native-launch"] if getattr(sys, "frozen", False)
                  else [sys.executable, "-m", "core.native_launcher"])
        try:
            super().__init__([
                *prefix, "--owned-client", str(self._directory),
                str(owner[0]), str(owner[1]), "--", *command,
            ], **kwargs)
        except BaseException:
            retired = self._directory.with_name(".done-" + self._directory.name)
            self._directory.rename(retired)
            (retired / "record.json").unlink()
            retired.rmdir()
            raise

    def terminate(self) -> None:
        """只发送本次客户端的取消请求，helper 确认客户端退出后才退出。"""
        if self.poll() is None:
            (self._directory / "cancel").touch()

    def poll(self):
        """helper 已退出且登记确认客户端收口才交付终态，随后回收本次临时文件。"""
        code = super().poll()
        if code is None or self._confirmed_exit:
            return code
        try:
            record = json.loads((self._directory / "record.json").read_text(encoding="utf-8"))
            if record.get("phase") != "done" or (
                "client" in record and _alive(record["client"])
            ):
                return None
            self._confirmed_exit = True
            # 先原子移出活动集合，再清理文件；worker 在 unlink 间退出不会留下
            # 缺失 record 的活动目录，退休目录由运行配置目录的最终清理兜底。
            retired = self._directory.with_name(".done-" + self._directory.name)
            self._directory.rename(retired)
            for name in ("record.json", "record.tmp", "cancel"):
                (retired / name).unlink(missing_ok=True)
            retired.rmdir()
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            return code if self._confirmed_exit else None
        return code

    def wait(self, timeout=None):
        """等待可确认的 helper/客户端终态，损坏或失败登记不能伪装完成。"""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            code = self.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, float(timeout or 0))
            time.sleep(0.01)

    def kill(self) -> None:
        """有界等待精确客户端清理；失败抛错，不能强杀 helper 丢失直接客户端。"""
        self.terminate()
        self.wait(timeout=2)

    def stop(self, timeout: float) -> bool:
        """共享上层时限，未收到 helper 退出确认时继续保留资源。"""
        try:
            self.terminate()
            self.wait(timeout=max(0.0, timeout))
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False


class OwnedWorkerProcess:
    """worker 和显式登记客户端共享退出状态；后代服务不属于此资源集合。"""

    def __init__(self, process: subprocess.Popen, directory: str):
        self._process = process
        self._directory = Path(directory)
        self._remote_failure_seen = False
        self._cleanup_owner: object | None = None
        self._confirmed_code: int | None = None

    def hold_cleanup_owner(self, owner: object) -> None:
        """跟踪表保留临时目录所有者，避免业务 runner 被释放后 finalizer 删除残留证据。"""
        self._cleanup_owner = owner

    def __getattr__(self, name):
        return getattr(self._process, name)

    @property
    def returncode(self):
        """对外退出码和资源归零共享确认边界，父进程退出码不能绕过登记检查。"""
        return self.poll()

    def poll(self):
        """本机集合退出后发布业务码；远端未确认是失败，不伪装本机进程仍存活。"""
        if self._confirmed_code is not None:
            return self._confirmed_code
        code = self._process.poll()
        if code is None:
            return None
        try:
            for directory in self._directory.iterdir():
                if directory.name.startswith(".done-"):
                    continue
                if directory.name.startswith("remote-"):
                    self._remote_failure_seen = True
                    continue
                record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
                if record.get("phase") != "done" or "helper" not in record:
                    return None
                if any(_alive(record[key]) for key in ("helper", "client") if key in record):
                    return None
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            return None
        return code or (1 if self._remote_failure_seen else 0)

    def resources_released(self) -> bool:
        """业务已结束仍可有远端租约义务；活动表必须等租约确认后才解除登记。"""
        if self._confirmed_code is not None:
            return True
        code = self.poll()
        if code is None:
            return False
        try:
            if any(path.name.startswith("remote-") for path in self._directory.iterdir()):
                return False
        except OSError:
            return False
        self._confirmed_code = code
        return True

    def wait(self, timeout=None):
        """在同一等待预算内观察整个显式集合，不因父进程先退出而提前返回。"""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            code = self.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, float(timeout or 0))
            time.sleep(0.01)

    def stop(self, timeout: float) -> bool:
        """先终止 worker 封闭新建，再等待客户端 helper 自行清理，失败保留登记。"""
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=min(0.5, max(0.0, timeout) / 2))
                except subprocess.TimeoutExpired:
                    # 只升级精确 worker 句柄；客户端由各 helper 清理，独立服务不受影响。
                    self._process.kill()
            self.wait(timeout=max(0.0, deadline - time.monotonic()))
            return self.resources_released()
        except (OSError, subprocess.TimeoutExpired):
            return False


def launch_owned_client(argv: list[str]) -> int:
    """内部入口先登记后创建，只回收直接客户端，独立 ADB 服务可以继续运行。"""
    if len(argv) < 6 or argv[4] != "--":
        return 2
    directory = Path(argv[1])
    owner = [int(argv[2]), float(argv[3])]
    record = {"owner": owner, "helper": _identity(os.getpid()), "phase": "starting"}
    child = None
    try:
        _write_record(directory, record)
        if not _alive(owner) or (directory / "cancel").exists():
            return 130
        with ExitStack() as streams:
            options = {}
            if sys.platform == "win32":
                from core.native_launcher import _kernel, _startup_info, sanitize_environment
                if not _kernel().SetDllDirectoryW(None):
                    return 2
                options = {
                    "startupinfo": _startup_info(streams), "close_fds": True,
                    "creationflags": subprocess.CREATE_NO_WINDOW,
                    "env": sanitize_environment(dict(os.environ), getattr(sys, "_MEIPASS", "")),
                }
            elif sys.platform == "linux" and getattr(sys, "frozen", False):
                from core.native_process import native_tool_environment
                options = {"env": native_tool_environment(dict(os.environ))}
            child = subprocess.Popen(argv[5:], **options)
        try:
            record["client"] = _identity(child.pid)
        except psutil.NoSuchProcess:
            # 极短客户端可能已退出；Popen 持有本次内核句柄，真实退出码仍然有效。
            if child.poll() is None:
                raise
        record["phase"] = "running"
        _write_record(directory, record)
        while child.poll() is None:
            if not _alive(owner) or (directory / "cancel").exists():
                child.kill()
            try:
                child.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                continue
        code = child.returncode
        return code - (1 << 32) if sys.platform == "win32" and code > 0x7FFFFFFF else code
    except (OSError, ValueError, psutil.Error):
        return 2
    finally:
        # 创建后的任何异常都必须先回收直接客户端；失败不得写 done 伪造归零。
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        record["phase"] = "done"
        _write_record(directory, record)
