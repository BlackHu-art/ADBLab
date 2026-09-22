"""提供 ADBLab Remote 页签使用的无界面 scrcpy 服务。"""

import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.adb_dimensions import parse_wm_size
from core.adb_query import query_timeout
from core.exec import CommandRunner, ExecHandle, ProcessRunner, adb_runtime
from core.scrcpy_session import cleanup_session_tunnels, has_active_helpers
from utils.runtime_tools import bundled_tool_path
from utils.scrcpy_bridge import resolve_scrcpy_bridge
from utils.tool_manifest import get_tool_bundle, macos_tool_candidates
from utils.user_data import user_data_root

from .scrcpy_args import build_scrcpy_args
from .types import PreflightResult, ScrcpyConfig, ScrcpyLaunchPlan, ScrcpyToolError

_port_lock = threading.Lock()
_reserved_ports: set[int] = set()
# 等待 helper 释放租约的上限：helper 正常在父进程消失后约 1 秒退出，慢链路下上传
# 仍可能更久；超预算按清理失败登记，端口与会话目录留给既有重试入口处理。
_HELPER_EXIT_BUDGET = 30.0


def _reserve_port() -> int:
    """跨服务实例保留独立端口，避免 Windows scrcpy 的 SO_REUSEADDR 混接设备。"""
    with _port_lock:
        for _attempt in range(64):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                exclusive_option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if exclusive_option is not None:
                    probe.setsockopt(socket.SOL_SOCKET, exclusive_option, 1)
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
                if port not in _reserved_ports:
                    _reserved_ports.add(port)
                    return port
    raise OSError("No free port is available for this mirror session.")


@dataclass
class _BridgeSession:
    """保留本次子进程环境及清理线程，直到系统确认线程已经结束。"""

    environment: dict[str, str]
    folder: Path | None
    port: int | None = None
    process: ExecHandle | None = None
    thread: threading.Thread | None = None
    cleanup_failed: bool = False
    starting: bool = True
    output_unclaimed: bool = False


class ScrcpyService:
    """在不依赖 Qt 控件的前提下准备并管理 scrcpy 进程。"""

    FPS_PATTERN = re.compile(r"\[(\d+\.?\d*)\s*fps\]")

    def __init__(
        self,
        process_runner: ProcessRunner | None = None,
        command_runner: type[CommandRunner] = CommandRunner,
    ):
        self.process_runner = process_runner or ProcessRunner()
        self.command_runner = command_runner
        self._version_cache: dict[str, str] = {}
        self._bridge_sessions: dict[str, _BridgeSession] = {}
        self._bridge_lock = threading.Lock()

    def run_command(
        self, cmd: list[str], timeout: float = 5, *, deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
        """预检共用启动预算；ADB/scrcpy 即使改名也须隔离，取消后停止后续查询。"""
        self._check_budget(deadline, cancelled)
        if deadline is not None:
            timeout = min(timeout, max(0, deadline - time.monotonic()))
        if cancelled is None:
            result = self.command_runner.run(cmd, timeout=timeout, native_tool=True)
        else:
            result = self.command_runner.run(
                cmd, timeout=timeout, cancelled=cancelled, native_tool=True,
            )
        self._check_budget(deadline, cancelled)
        return result

    @staticmethod
    def _check_budget(deadline: float | None, cancelled: Callable[[], bool] | None) -> None:
        """取消优先于超时，失败不能退化成继续启动的预检警告。"""
        if cancelled is not None and cancelled():
            raise InterruptedError("scrcpy launch cancelled")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("scrcpy launch preflight timed out")

    def resolve_executable(self) -> str:
        """显式路径即使无效也原样交给现有失败边界，禁止静默改用另一份工具。"""
        override = os.environ.get("SCRCPY_PATH", "").strip()
        if override:
            return os.path.abspath(os.path.expanduser(override))
        platform_key = {"Windows": "win32", "Linux": "linux", "Darwin": "darwin"}.get(
            platform.system(), "unsupported",
        )
        bundle = get_tool_bundle(platform_key)
        if bundle is not None:
            executable = bundled_tool_path(bundle.directory, bundle.scrcpy)
            if platform_key == "win32" or os.path.isfile(executable):
                return executable
        found = shutil.which("scrcpy")
        if found:
            return found
        if platform_key == "darwin":
            for _source, executable in macos_tool_candidates("scrcpy"):
                if os.path.isfile(executable) and os.access(executable, os.X_OK):
                    return executable
        return "scrcpy"

    def version(
        self, exe: str, *, deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        cached = self._version_cache.get(exe)
        if cached:
            return cached
        try:
            result = self.run_command(
                [exe, "--version"], timeout=3, deadline=deadline, cancelled=cancelled,
            )
            match = re.search(r"\bscrcpy\s+(\d+\.\d+(?:\.\d+)?)", result.output)
            if not result.success or match is None:
                raise ScrcpyToolError()
            version = match.group(1)
        except (InterruptedError, TimeoutError):
            raise
        except (OSError, ScrcpyToolError) as error:
            raise ScrcpyToolError() from error
        self._version_cache[exe] = version
        return version

    def device_info(
        self, adb: str, device: str, *, deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        try:
            result = self.run_command(
                [adb, "-s", device, "shell", "wm size"],
                timeout=query_timeout(device, 5, adb_path=adb),
                deadline=deadline, cancelled=cancelled,
            )
            dimensions = parse_wm_size(result.output or "") if result.success else None
            if dimensions:
                return "x".join(dimensions)
        except (InterruptedError, TimeoutError):
            raise
        except Exception:
            pass
        return ""

    def preflight_check(
        self, adb: str, device: str, *, deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> PreflightResult:
        """只查询必要的设备响应，不让附加测速阻塞启动路径。"""
        messages: list[tuple[str, str]] = []
        try:
            result = self.run_command(
                [adb, "-s", device, "shell", "echo ok"],
                timeout=query_timeout(device, 5, adb_path=adb),
                deadline=deadline, cancelled=cancelled,
            )
            if not result.success or (result.output or "").strip() != "ok":
                messages.append(("WARNING", f"Device {device} not responding"))
                return PreflightResult(False, messages)

            return PreflightResult(True, messages)
        except (InterruptedError, TimeoutError):
            raise
        except Exception as exc:
            messages.append(("WARNING", f"Pre-flight failed: {exc}"))
            return PreflightResult(False, messages)

    def detect_encoder(
        self, adb: str, device: str, *, deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str | None:
        try:
            result = self.run_command(
                [adb, "-s", device, "shell", "dumpsys media.codec"], timeout=8,
                deadline=deadline, cancelled=cancelled,
            )
            for line in (result.output or "").splitlines():
                lowered = line.lower()
                if "h264" in lowered and "encoder" in lowered:
                    name = line.strip().split()[0]
                    if "OMX" in name or name.startswith("c2."):
                        return name
        except (InterruptedError, TimeoutError):
            raise
        except Exception:
            pass
        return None

    @staticmethod
    def require_client(path: str | None) -> str:
        """配置冻结前验证精确客户端，不允许 scrcpy 再按 PATH 自行选择。"""
        if not path or not os.path.isabs(path) or not os.path.isfile(path):
            raise FileNotFoundError("ADB 客户端不可用，请在设置中重新选择客户端后启动投屏。")
        return path

    def build_launch_plan(
        self, config: ScrcpyConfig, *, timeout: float = 20,
        cancelled: Callable[[], bool] | None = None,
    ) -> ScrcpyLaunchPlan:
        """在单次预算内完成预检；取消和预算耗尽直接终止，不发布启动计划。"""
        self.require_client(config.adb)
        deadline = time.monotonic() + max(0, timeout)
        self._check_budget(deadline, cancelled)
        messages: list[tuple[str, str]] = []
        version = self.version(config.exe, deadline=deadline, cancelled=cancelled)
        messages.append(("INFO", f"scrcpy v{version}"))

        # 离线设备不再读取尺寸，兼容现有允许 scrcpy 自行报告连接错误的行为。
        preflight = self.preflight_check(
            config.adb, config.device, deadline=deadline, cancelled=cancelled,
        )
        messages.extend(preflight.messages)
        if not preflight.success:
            messages.append(("WARNING", "Pre-flight check failed - launching anyway..."))
            device_info = ""
        else:
            device_info = self.device_info(
                config.adb, config.device, deadline=deadline, cancelled=cancelled,
            )

        encoder = None
        if config.hw_encoder:
            encoder = self.detect_encoder(
                config.adb, config.device, deadline=deadline, cancelled=cancelled,
            )
            if encoder:
                messages.append(("INFO", f"Using encoder: {encoder}"))
            else:
                messages.append(("WARNING", "No hardware encoder found, using default"))

        return ScrcpyLaunchPlan(
            args=build_scrcpy_args(config, encoder),
            device_info=device_info,
            version=version,
            encoder=encoder,
            messages=messages,
            **self._launch_backend(config, version),
        )

    def _launch_backend(self, config: ScrcpyConfig, version: str) -> dict:
        """在启动前冻结受支持设备的执行方式，仅给 scrcpy 子进程覆盖 ADB。"""
        environment = dict(os.environ)
        environment["ADB"] = config.adb
        runtime = adb_runtime()
        helper = resolve_scrcpy_bridge()
        server = Path(config.exe).parent / "scrcpy-server"
        direct = (
            version == "4.1" and not config.extra_args and helper is not None
            and not environment.get("SCRCPY_SERVER_PATH")
            and runtime is not None and runtime.can_shell_fast(config.adb, config.device)
            and server.is_file()
        )
        if direct:
            assert helper is not None
            environment.update({
                "ADB": helper,
                "ADBLAB_SCRCPY_SERIAL": config.device,
                "ADBLAB_SCRCPY_SERVER": str(server.resolve()),
                "ADBLAB_SCRCPY_OWNER_PID": str(os.getpid()),
                "ADBLAB_SCRCPY_PORT_RANGE": "27183:27199",
            })
        return {"env": environment, "backend": "direct" if direct else "native"}

    def start_plan(self, key: str, plan: ScrcpyLaunchPlan) -> ExecHandle:
        """启动已经冻结的计划，后续设置变化不改向本次进程。"""
        if self.is_active(key):
            raise RuntimeError("The previous mirror session is still active.")
        environment = dict(plan.env) if plan.env is not None else None
        folder = None
        if plan.backend == "direct":
            if environment is None:
                raise ValueError("A direct mirror requires a frozen environment.")
            root = user_data_root() / "scrcpy-sessions"
            root.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="session-", dir=root))
            environment["ADBLAB_SCRCPY_SESSION_FILE"] = str(folder / "session.json")
        session = _BridgeSession(environment or {}, folder)
        try:
            with self._bridge_lock:
                if key in self._bridge_sessions:
                    raise RuntimeError("A concurrent mirror launch already owns this key.")
                self._bridge_sessions[key] = session
            args = list(plan.args)
            # 用户显式指定端口时沿用其配置，普通界面启动由本应用分配独立端口。
            explicit_port = any(
                item in {"--port", "-p"} or item.startswith(("--port=", "-p"))
                for item in args[1:]
            )
            if not explicit_port:
                session.port = _reserve_port()
                args.append(f"--port={session.port}")
                if plan.backend == "direct":
                    assert environment is not None
                    environment["ADBLAB_SCRCPY_PORT_RANGE"] = f"{session.port}:{session.port}"
            process = self.process_runner.start(
                key, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="ignore", bufsize=1, env=environment,
                native_tool=True,
            )
        except Exception:
            with self._bridge_lock:
                if self._bridge_sessions.get(key) is session:
                    self._bridge_sessions.pop(key)
            self._release_port(session)
            if session.folder is not None:
                self._remove_session_folder(session.folder)
            raise
        with self._bridge_lock:
            session.process = process
            try:
                session.thread = threading.Thread(
                    target=self._finish_bridge_session, args=(key, process, session),
                    name="scrcpy-session-cleanup", daemon=True,
                )
                session.starting = False
                session.thread.start()
            except Exception:
                session.starting = False
                session.thread = None
                session.cleanup_failed = True
                # 启动没有返回句柄，界面尚不能创建 reader；重试清理必须接管这两个流。
                session.output_unclaimed = True
                self.process_runner.request_stop(key)
                raise
        return process

    @staticmethod
    def _release_port(session: _BridgeSession) -> None:
        """进程和隧道均完成清理后释放端口；失败会话保留其预留直到重试成功。"""
        if session.port is not None:
            with _port_lock:
                _reserved_ports.discard(session.port)

    @staticmethod
    def _remove_session_folder(folder: Path) -> None:
        """只删除本次 mkdtemp 创建的会话平面文件，不递归删除其他用户目录。"""
        for path in folder.iterdir():
            path.unlink()
        folder.rmdir()

    def _finish_bridge_session(
        self, key: str, process: ExecHandle, session: _BridgeSession,
    ) -> None:
        """后台等待父进程和 helper 租约释放，再清理本会话端口；失败保留诊断状态。"""
        import logging

        try:
            process.wait()
            if session.output_unclaimed:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            # 进程退出与隧道清理分别归属；旧代次只能释放自身句柄，reader 自行关闭管道。
            self.process_runner.release_finished(key, process)
            if session.folder is not None:
                session_file = Path(session.environment["ADBLAB_SCRCPY_SESSION_FILE"])
                helper_deadline = time.monotonic() + _HELPER_EXIT_BUDGET
                while has_active_helpers(session_file):
                    if time.monotonic() >= helper_deadline:
                        raise TimeoutError("Scrcpy helper did not release its lease in time.")
                    time.sleep(0.1)
                cleanup_session_tunnels(session.environment, timeout=3.0)
                self._remove_session_folder(session.folder)
            self._release_port(session)
        except Exception as exc:
            # 不打印设备、路径和远端输出；失败目录保留原会话身份，不能宣称端口已清理。
            session.cleanup_failed = True
            logging.getLogger(__name__).warning(
                "scrcpy session cleanup could not be confirmed (%s)", type(exc).__name__,
            )

    def _wait_bridge_session(self, key: str, timeout: float) -> None:
        """调用方在后台停止任务中等待；不在 GUI 线程执行进程或网络等待。"""
        with self._bridge_lock:
            session = self._bridge_sessions.get(key)
            if (
                session is not None and session.cleanup_failed and timeout > 0
                and (session.thread is None or not session.thread.is_alive())
                and key not in self.process_runner.active_keys
            ):
                assert session.process is not None
                session.cleanup_failed = False
                session.thread = threading.Thread(
                    target=self._finish_bridge_session, args=(key, session.process, session),
                    name="scrcpy-session-cleanup", daemon=True,
                )
                try:
                    session.thread.start()
                except RuntimeError:
                    session.thread = None
                    session.cleanup_failed = True
        if session is not None and session.thread is not None:
            session.thread.join(max(0.0, timeout))

    def start(self, key: str, args: list[str]) -> ExecHandle:
        """启动由 ``ProcessRunner`` 跟踪的 scrcpy 长进程。"""
        return self.process_runner.start(
            key,
            args,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            native_tool=True,
        )

    def stop(self, key: str, timeout: float = 2.0) -> int | None:
        """等待 scrcpy 在时限内退出，必要时由 ``ProcessRunner`` 强制清理。"""
        deadline = time.monotonic() + max(0.0, timeout)
        result = self.process_runner.stop(key, timeout=timeout)
        self._wait_bridge_session(key, deadline - time.monotonic())
        return result if not self.is_active(key) else None

    def request_stop(self, key: str) -> bool:
        """只发送停止请求，不等待进程退出。"""
        requested = self.process_runner.request_stop(key)
        return requested or self.is_active(key)

    def force_stop(self, key: str, timeout: float) -> bool:
        """强制停止 scrcpy，并仅在进程已解除跟踪时确认成功。"""
        deadline = time.monotonic() + max(0.0, timeout)
        attempted = bool(self.process_runner.force_stop(key, timeout))
        with self._bridge_lock:
            had_session = key in self._bridge_sessions
        self._wait_bridge_session(key, deadline - time.monotonic())
        return (attempted or had_session) and not self.is_active(key)

    def is_active(self, key: str) -> bool:
        """父进程结束后，仍将 helper 退出和端口清理纳入关闭屏障。"""
        with self._bridge_lock:
            session = self._bridge_sessions.get(key)
            if session is not None:
                if session.starting or session.cleanup_failed or (
                    session.thread is not None and session.thread.is_alive()
                ):
                    return True
                self._bridge_sessions.pop(key, None)
        return key in self.process_runner.active_keys

    @classmethod
    def parse_fps(cls, line: str) -> str | None:
        match = cls.FPS_PATTERN.search(line)
        return f"{match.group(1)} fps" if match else None
