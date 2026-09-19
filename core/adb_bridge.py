"""为 ADBLab 提供轻量的 ADB Shell 调用封装。

ADB 路径由 utils.adb_resolver 统一解析；实例未显式指定路径时按当前解析结果惰性取值，
使「重新检测」之后无需重建面板即可切换到新的客户端。
"""

import subprocess
import threading
import time
from collections.abc import Callable

from core.adb_dimensions import parse_wm_size
from core.exec import (
    CommandResult,
    CommandRunner,
    ExecHandle,
    ProcessRunner,
    adb_runtime,
    require_adb_program,
)
from core.exec import resolve_adb_program as adb_path


class ADBInputSession:
    """维护持久化的 adb shell 会话，降低输入命令延迟。

    会话进程通过 ProcessRunner 注册进实例与全局跟踪表；关闭先终止进程，
    解除管道背压后再等待发送锁，避免输入生产者和收尾互相等待。
    """

    def __init__(
        self,
        adb: str,
        device_id: str | None = None,
        runner: ProcessRunner | None = None,
    ):
        self.adb = adb
        self.device_id = device_id
        self._proc: ExecHandle | None = None
        self._lock = threading.Lock()
        self._retired = threading.Event()
        self._stop_requested = threading.Event()
        self._starting = threading.Event()
        self._runner = runner or ProcessRunner()

    @property
    def _key(self) -> str:
        return f"adb-input-session-{id(self)}"

    def send(
        self, command: str, *, cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """写入持久管道；失败可能已部分发送，调用方不得据此重放输入。"""
        with self._lock:
            if self._retired.is_set() or (cancelled is not None and cancelled()):
                return False
            proc = self._ensure_process()
            if (not proc or not proc.stdin or self._retired.is_set()
                    or (cancelled is not None and cancelled())):
                return False
            try:
                proc.stdin.write(f"input {command}\n")
                proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                # 写入失败可能留下部分缓冲，不能以 exit 再次刷新未知输入。
                self._close_locked(graceful=False)
                return False

    def retire(self) -> None:
        """永久关闭后续输入准入；Event 不等待管道锁，GUI 可先封口再提交后台释放。"""
        self._retired.set()

    def close(self):
        """后台收口；终止请求不等待管道锁，未退出的进程仍保留归属。"""
        self.request_stop()
        with self._lock:
            self._close_locked(graceful=False)

    def request_stop(self) -> None:
        """永久封口并请求终止本会话进程，不等待正在 write/flush 的发送锁。"""
        self.retire()
        if not self._stop_requested.is_set():
            self._stop_requested.set()
            self._runner.request_stop(self._key)

    def force_stop(self, timeout: float) -> bool:
        """只强停本会话唯一进程键；不以相同设备的新会话替代旧资源。"""
        self.retire()
        return self._runner.force_stop(self._key, timeout=timeout)

    def is_running(self) -> bool:
        """无需取得发送锁即可查询进程；终止失败不能丢弃资源归属。"""
        proc = self._proc
        return self._starting.is_set() or (proc is not None and proc.poll() is None)

    def warm(self, *, cancelled: Callable[[], bool] | None = None) -> bool:
        """在第一条真实输入命令前预先打开持久 Shell。"""
        with self._lock:
            if self._retired.is_set() or (cancelled is not None and cancelled()):
                return False
            proc = self._ensure_process()
            return bool(
                proc and proc.stdin and proc.poll() is None
                and not self._retired.is_set()
                and not (cancelled is not None and cancelled())
            )

    def _ensure_process(self) -> ExecHandle | None:
        if self._retired.is_set():
            return None
        if self._proc and self._proc.poll() is None:
            return self._proc
        self._close_locked()
        cmd = [self.adb]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.append("shell")
        self._starting.set()
        try:
            # 退休列表可能与启动并发清理；先登记启动状态，再确认仍有创建准入。
            if self._retired.is_set():
                return None
            try:
                self._proc = self._runner.start(
                    self._key,
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
            except Exception:
                self._proc = None
                return None
            if self._retired.is_set():
                # stop 可能先于 start 的进程登记，登记后必须补发，且不得发送输入。
                self._runner.request_stop(self._key)
                return None
            return self._proc
        finally:
            self._starting.clear()

    def _close_locked(self, *, graceful: bool = True):
        proc = self._proc
        if proc is None:
            return
        try:
            if graceful and proc.stdin and proc.poll() is None:
                proc.stdin.write("exit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            self._runner.stop(self._key, timeout=1)
        except Exception:
            pass
        if proc.poll() is not None:
            self._proc = None


class ADBBridge:
    """封装 ADB Shell、输入、屏幕尺寸和设备列表命令。"""

    def __init__(self, path: str | None = None):
        # 显式路径冻结在实例上；未指定时惰性读取统一解析结果。缺少 ADB 不再阻止
        # 窗口构造，改由命令失败结果、设置页 ADB 状态和环境探测提示用户。
        self._explicit_path = path
        self._process_runner = ProcessRunner()
        self._input_sessions: dict[str, ADBInputSession] = {}
        self._input_sessions_lock = threading.Lock()
        self._retired_input_sessions: list[ADBInputSession] = []
        self._input_closing = threading.Event()

    @property
    def path(self) -> str | None:
        """返回当前 ADB 可执行文件；未显式指定时跟随统一解析缓存。"""

        return self._explicit_path if self._explicit_path is not None else adb_path()

    def shell(
        self, command: str, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> CommandResult:
        """执行有界 Shell 命令，按调用方取消信号收口并返回标准化结果。"""
        path = self.path
        if not path:
            return CommandResult(
                success=False, error="ADB 客户端不可用，请在设置中重新选择客户端。",
            )
        cmd = [path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", command])
        if cancelled is None:
            return CommandRunner.run(cmd, timeout=15)
        return CommandRunner.run(cmd, timeout=15, cancelled=cancelled)

    def can_input_fast(self, device_id: str | None = None) -> bool:
        """读取应用运行实例对当前设备的直连选择，不隐式创建实例或探测设备。"""
        runtime = adb_runtime()
        path = self.path
        return bool(path and device_id and runtime and runtime.can_shell_fast(path, device_id))

    def shell_input(
        self, command: str, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """向设备 Shell 发送 input 命令，例如 keyevent 或 swipe。

        已验证设备经统一执行器直连并按远端结果返回；其他设备复用持久会话。
        仅尚未写入输入的会话准备失败可以降级，写入或直连发送后的失败不重放。
        取消只阻止后续发送并收口在途请求，不表示已执行的设备操作被撤销。
        """
        if self._input_closing.is_set() or (cancelled is not None and cancelled()):
            return False
        if not self.path:
            return False
        cancel_options = {"cancelled": cancelled} if cancelled is not None else {}
        if not self.can_input_fast(device_id):
            try:
                session = self._input_session(device_id)
            except FileNotFoundError:
                return False
            if session.warm(**cancel_options):
                return session.send(command, **cancel_options)
        if self._input_closing.is_set() or (cancelled is not None and cancelled()):
            return False
        path = self.path
        if not path:
            return False
        cmd = [path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", f"input {command}"])
        if cancelled is None:
            return CommandRunner.run(cmd, timeout=15).success
        return CommandRunner.run(cmd, timeout=15, cancelled=cancelled).success

    def warm_input_session(
        self, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """直连能力已就绪时直接返回；仅原生后端预建会话，始终不发送用户输入。"""
        if self._input_closing.is_set() or (cancelled is not None and cancelled()):
            return False
        if not self.path:
            return False
        if self.can_input_fast(device_id):
            return True
        cancel_options = {"cancelled": cancelled} if cancelled is not None else {}
        try:
            return self._input_session(device_id).warm(**cancel_options)
        except FileNotFoundError:
            return False

    def close_input_sessions(self, device_id: str | None = None):
        """关闭持久输入 Shell 会话，供面板或服务停止时清理资源。"""
        with self._input_sessions_lock:
            if device_id is None:
                sessions = list(self._input_sessions.values()) + self._retired_input_sessions
                self._input_sessions.clear()
                self._retired_input_sessions = []
            else:
                session = self._input_sessions.pop(self._session_key(device_id), None)
                sessions = [session] if session else []
            for session in sessions:
                if session not in self._retired_input_sessions:
                    self._retired_input_sessions.append(session)
        self._close_sessions(sessions)

    def _close_sessions(self, sessions) -> None:
        first_error = None
        for session in sessions:
            try:
                session.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        self._prune_retired_input_sessions()
        if first_error is not None:
            raise first_error

    def _all_input_sessions(self) -> tuple[ADBInputSession, ...]:
        with self._input_sessions_lock:
            return tuple(dict.fromkeys((
                *self._input_sessions.values(), *self._retired_input_sessions,
            )))

    def request_stop_input_sessions(self) -> None:
        """关闭整个桥的输入准入，并在等待 producer 前解除所有持久管道背压。"""
        self._input_closing.set()
        first_error = None
        for session in self._all_input_sessions():
            try:
                session.request_stop()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def force_stop_input_sessions(self, timeout: float) -> bool:
        """在同一总时限内强停当前及已退休输入资源，仍按各自进程身份定位。"""
        self._input_closing.set()
        deadline = time.monotonic() + max(0.0, timeout)
        attempted = False
        first_error = None
        for session in self._all_input_sessions():
            try:
                if session.is_running():
                    stopped = session.force_stop(max(0.0, deadline - time.monotonic()))
                    attempted = stopped or attempted
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
        return attempted

    def input_sessions_running(self) -> bool:
        """已从设备映射摘除但终止未确认的会话同样纳入停止屏障。"""
        return any(session.is_running() for session in self._all_input_sessions())

    def _prune_retired_input_sessions(self) -> None:
        with self._input_sessions_lock:
            self._retired_input_sessions = [
                session for session in self._retired_input_sessions if session.is_running()
            ]

    def detach_input_sessions(self) -> list[ADBInputSession]:
        """仅摘除当前会话；调用方把返回资源交给既有后台队列关闭，不阻塞 GUI。"""
        with self._input_sessions_lock:
            sessions = list(self._input_sessions.values())
            self._input_sessions.clear()
            for session in sessions:
                session.retire()
            self._retired_input_sessions.extend(sessions)
            return sessions

    def close_retired_input_sessions(self) -> None:
        """在既有后台队列关闭已摘除会话；未提交清理时仍由最终关闭接管资源。"""
        with self._input_sessions_lock:
            sessions = tuple(self._retired_input_sessions)
        self._close_sessions(sessions)

    def _input_session(self, device_id: str | None) -> ADBInputSession:
        key = self._session_key(device_id)
        obsolete = None
        with self._input_sessions_lock:
            if self._input_closing.is_set():
                raise FileNotFoundError("ADB 输入会话正在关闭")
            path = self.path
            if not path:
                require_adb_program()
                raise FileNotFoundError("ADB 客户端不可用")
            session = self._input_sessions.get(key)
            if session is not None and session.adb != path:
                obsolete = session
                obsolete.retire()
                self._retired_input_sessions.append(obsolete)
                session = None
            if session is None:
                session = ADBInputSession(path, device_id, runner=self._process_runner)
                self._input_sessions[key] = session
        # 此入口只由输入/预热后台任务消费；摘除旧映射后等待既有输入完成，不重放命令。
        if obsolete is not None:
            obsolete.close()
        return session

    @staticmethod
    def _session_key(device_id: str | None) -> str:
        return device_id or "__default__"

    def get_dimensions(
        self, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ):
        """通过可取消的 wm size 获取屏幕尺寸，返回宽高列表或 None。"""
        try:
            result = (
                self.shell("wm size", device_id=device_id)
                if cancelled is None
                else self.shell("wm size", device_id=device_id, cancelled=cancelled)
            )
            return parse_wm_size(result.output) if result.success else None
        except Exception:
            return None

    def devices(self) -> list[list[str]]:
        """返回由设备序列号和连接状态组成的设备列表。"""
        path = self.path
        if not path:
            return []
        result = CommandRunner.run([path, "devices"], timeout=15)
        if not result.success:
            return []
        out = result.output
        return [line.split("\t") for line in out.strip().splitlines()[1:] if line.strip()]
