"""提供 Monkey、Bugreport、截图、设备日志和 ANR 拉取等测试诊断能力。

本模块只依赖核心 adb_model，避免模型之间形成循环依赖。
"""

import logging
import os
import random
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtGui import QImageReader

from core.adb_query import query_timeout
from core.exec import CommandRunner, ProcessRunner
from utils.adb_values import normalize_android_package
from utils.archive import safe_extract_zip
from utils.atomic_text import atomic_write_text
from utils.resource_path import resource_path

from .adb_model import ADBModelCore, async_command
from .base.focus_detector import detect_current_package


@dataclass
class _MonkeyBatchState:
    """保存已提交批次的取消与执行状态，排队阶段也必须保留停止意图。"""

    batch_id: str
    running: bool = False
    cancelled: bool = False


class ADBTesting(ADBModelCore):
    """封装 Monkey、Bugreport、截图、日志获取和 ANR 拉取操作。"""

    def __init__(self):
        super().__init__()
        self._aborted_devices = set()
        self._abort_lock = threading.Lock()
        self._abort_condition = threading.Condition(self._abort_lock)
        self._monkey_batches: dict[str, _MonkeyBatchState] = {}
        self._monkey_archive_results: dict[tuple[str, str], dict] = {}
        self._procs = ProcessRunner()
        self._process_lifecycle_lock = threading.Lock()

    def shutdown(self):
        """终止 Monkey/logcat 等测试诊断进程，供应用退出时统一调用。"""
        self.begin_shutdown()
        with self._abort_condition:
            self._aborted_devices.add("*")
            self._abort_condition.notify_all()
        with self._process_lifecycle_lock:
            self._procs.stop_all()
            with self._abort_condition:
                self._monkey_batches.clear()

    def prepare_monkey_batch(self, device_ip: str, batch_id: str) -> bool:
        """排队前登记设备批次；关闭或已有批次时拒绝，不等待外部进程。"""

        with self._abort_condition:
            if self.is_shutting_down() or device_ip in self._monkey_batches:
                return False
            self._monkey_batches[device_ip] = _MonkeyBatchState(batch_id)
            self._aborted_devices.discard(device_ip)
            return True

    def monkey_run_archive_snapshot(
        self, device_ip: str, batch_id: str, *, consume: bool = False,
    ) -> dict | None:
        """读取当前批次的归档快照，供 GUI 关闭后拒收普通回调时补齐终态。"""
        with self._abort_condition:
            key = (device_ip, batch_id)
            result = self._monkey_archive_results.get(key)
            if result is None:
                return None
            if consume:
                self._monkey_archive_results.pop(key, None)
            return dict(result)

    def _remember_monkey_archive_result(self, result: dict) -> None:
        """在工作线程保存纯数据快照；普通 Controller 终态消费后立即释放。"""
        with self._abort_condition:
            key = (str(result["device_ip"]), str(result["batch_id"]))
            self._monkey_archive_results[key] = dict(result)
            # 无 Controller 的直接调用仍有界，不能因多次诊断保留无限历史。
            while len(self._monkey_archive_results) > 200:
                terminal_key = next((
                    item for item, value in self._monkey_archive_results.items()
                    if value.get("terminal")
                ), None)
                if terminal_key is None:
                    break
                self._monkey_archive_results.pop(terminal_key)

    def discard_prepared_monkey_batch(self, device_ip: str, batch_id: str) -> None:
        """提交失败时释放尚未执行的同批登记，不影响已运行或其他批次。"""

        with self._abort_condition:
            state = self._monkey_batches.get(device_ip)
            if state is not None and state.batch_id == batch_id and not state.running:
                self._monkey_batches.pop(device_ip)
                self._aborted_devices.discard(device_ip)

    def _start_testing_process(
        self, key: str, cmd: list[str], *, stdout=None,
        monkey_batch: tuple[str, str] | None = None,
    ):
        """按 model 终态与 shutdown 原子排序启动测试长进程。"""

        with self._process_lifecycle_lock:
            if self.is_shutting_down():
                raise RuntimeError("Model is shutting down")
            if monkey_batch is not None:
                device_ip, batch_id = monkey_batch
                with self._abort_condition:
                    state = self._monkey_batches.get(device_ip)
                    if state is None or state.batch_id != batch_id or state.cancelled:
                        raise RuntimeError("Aborted by user")
            return self._procs.start(key, cmd, stdout=stdout)

    def _wait_for_monkey_abort(self, device_ip: str, timeout: float) -> bool:
        """可中断等待监控间隔，并在停止请求到达时立即唤醒。"""

        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._abort_condition:
            while device_ip not in self._aborted_devices and "*" not in self._aborted_devices:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._abort_condition.wait(remaining)
            return True

    def _get_current_package(
        self, device_ip: str, *, timeout: float = 15,
        cancelled: Callable[[], bool] | None = None, deadline: float | None = None,
    ) -> str:
        """前台读取继承运行批次的取消与截止时间，独立调用也响应模型关闭。"""
        result = detect_current_package(
            device_ip, timeout=timeout, deadline=deadline,
            cancelled=lambda: self.is_shutting_down() or bool(cancelled and cancelled()),
        )
        if result.get("success"):
            return result.get("package_name", "")
        return ""

    @staticmethod
    def _command_timed_out(command_result) -> bool:
        if bool(getattr(command_result, "timed_out", False)):
            return True
        error = str(getattr(command_result, "error", "") or "").strip().lower()
        return error.startswith("timeout(") or "timed out" in error

    def _probe_current_package(self, device_ip: str) -> dict:
        """前台与连通探针共享截止时间和本设备批次取消，不查询已取消或替换的批次。"""
        deadline = time.monotonic() + 15
        with self._abort_condition:
            owned_state = self._monkey_batches.get(device_ip)

        def stopped() -> bool:
            if self.is_shutting_down():
                return True
            with self._abort_condition:
                return (
                    device_ip in self._aborted_devices or "*" in self._aborted_devices
                    or (owned_state is not None and (
                        owned_state.cancelled
                        or self._monkey_batches.get(device_ip) is not owned_state
                    ))
                )

        def cancelled_result() -> dict:
            return {
                "success": False, "package_name": "", "timed_out": False,
                "cancelled": True, "error": "Aborted by user",
            }

        if stopped():
            return cancelled_result()
        try:
            package_name = self._get_current_package(
                device_ip, timeout=15, deadline=deadline, cancelled=stopped,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "package_name": "",
                "timed_out": True,
                "error": str(exc),
            }
        except Exception as exc:
            return {
                "success": False,
                "package_name": "",
                "timed_out": False,
                "error": str(exc),
            }

        if stopped():
            return cancelled_result()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "success": False, "package_name": "", "timed_out": True,
                "error": "Timeout(15s)",
            }
        if package_name:
            return {
                "success": True,
                "package_name": package_name,
                "timed_out": False,
                "error": "",
            }

        # 当前前台包名接口只返回解析后的字典；额外探测一次连接，确保监控决策仍包含
        # CommandRunner 的真实成功或超时状态。
        connectivity = CommandRunner.run(
            ["adb", "-s", device_ip, "shell", "echo", "ok"],
            timeout=min(query_timeout(device_ip, 5), remaining), cancelled=stopped,
        )
        if stopped():
            return cancelled_result()
        timed_out = self._command_timed_out(connectivity)
        error = str(getattr(connectivity, "error", "") or "").strip()
        if getattr(connectivity, "success", False):
            error = "No foreground package detected"
        elif not error:
            error = "Foreground package probe failed"
        return {
            "success": False,
            "package_name": "",
            "timed_out": timed_out,
            "error": error,
        }

    # 截图

    @async_command(long_running=True)
    def take_screenshot_async(
        self, device_ip: str, save_path: str, *, cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        """在单次预算内采集并验证完整 PNG，只有成功且未取消时原子发布最终文件。"""
        deadline = time.monotonic() + 30
        temporary = ""

        def stopped() -> bool:
            return self.is_shutting_down() or bool(cancelled and cancelled())

        def failure(message: str) -> dict:
            return {"success": False, "device_ip": device_ip, "error": message}

        try:
            if stopped():
                return failure("Cancelled")
            with tempfile.NamedTemporaryFile(
                dir=os.path.dirname(os.path.abspath(save_path)), prefix=".adblab-shot-",
                suffix=".part", delete=False,
            ) as staged:
                temporary = staged.name
            direct = CommandRunner.run_to_file(
                ["adb", "-s", device_ip, "exec-out", "screencap", "-p"],
                temporary, timeout=max(0, deadline - time.monotonic()), cancelled=stopped,
            )
            error = direct.error.lower()
            # 只在客户端明确不识别 exec-out 时启用旧设备兼容路径；传输中断或坏图不重拍。
            unsupported = (
                not direct.success and direct.returncode != 0 and "exec-out" in error
                and any(word in error for word in ("unknown command", "unrecognized command"))
            )
            if unsupported and not stopped():
                direct = self._capture_legacy_screenshot(device_ip, temporary, deadline, stopped)
            if stopped():
                return failure("Cancelled")
            if not direct.success:
                return failure(direct.error or "Screenshot failed")
            if not self._is_valid_png(temporary, decode=True):
                return failure("Invalid or incomplete screenshot")
            if stopped():
                return failure("Cancelled")
            if time.monotonic() >= deadline:
                return failure("Timeout(30s)")
            os.replace(temporary, save_path)
            temporary = ""
            return {"success": True, "device_ip": device_ip, "screenshot_path": save_path}
        except OSError:
            return failure("Unable to save screenshot")
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    # 清理失败不覆盖原始取消或采集错误，也不把本机路径放入结果和日志。
                    logging.getLogger(__name__).warning(
                        "Temporary screenshot cleanup failed (%s)", type(exc).__name__,
                    )

    def _capture_legacy_screenshot(self, device_ip, temporary, deadline, cancelled):
        """使用本任务独占的设备文件；必要清理独立有界，关闭取消仍由模型拥有。"""
        remote = f"/sdcard/adblab_screenshot_{uuid.uuid4().hex}.png"
        try:
            result = CommandRunner.run(
                ["adb", "-s", device_ip, "shell", "screencap", "-p", remote],
                timeout=max(0, deadline - time.monotonic()), cancelled=cancelled,
            )
            if not result.success:
                return result
            return CommandRunner.run(
                ["adb", "-s", device_ip, "pull", remote, temporary],
                timeout=max(0, deadline - time.monotonic()), cancelled=cancelled,
            )
        finally:
            # 用户取消或采集耗尽预算后仍回收唯一临时文件；模型关闭可中断本次清理。
            CommandRunner.run(
                ["adb", "-s", device_ip, "shell", "rm", "-f", remote],
                timeout=query_timeout(device_ip, 5), cancelled=self.is_shutting_down,
            )

    @staticmethod
    def _is_valid_png(path: str, *, decode: bool = False) -> bool:
        """检查 PNG 首尾边界；完整像素解码仅由采集工作线程请求，避免阻塞回调。"""
        try:
            with open(path, "rb") as image_file:
                if image_file.read(8) != b"\x89PNG\r\n\x1a\n":
                    return False
                image_file.seek(-12, os.SEEK_END)
                if image_file.read() != b"\x00\x00\x00\x00IEND\xaeB`\x82":
                    return False
            return not decode or not QImageReader(path, b"png").read().isNull()
        except OSError:
            return False

    # 设备日志

    @staticmethod
    def _oneshot_logcat_command(device_ip: str, option: str) -> list[str]:
        """保留 adb logcat 的主机标签过滤环境和设备默认缓冲区，仅允许有限操作。"""
        if option not in {"-c", "-d"}:
            raise ValueError("Invalid one-shot logcat option")
        # 与 AOSP 客户端一样传递 ANDROID_LOG_TAGS；作为设备 shell 值引用以防命令注入。
        tags = shlex.quote(os.environ.get("ANDROID_LOG_TAGS", ""))
        return ["adb", "-s", device_ip, "shell", f"ANDROID_LOG_TAGS={tags}", "logcat", option]

    @async_command(long_running=True)
    def retrieve_device_logs_async(self, device_ip: str, log_path: str) -> dict:
        try:
            r = self._run_readonly(self._oneshot_logcat_command(device_ip, "-d"), timeout=30)
            if not r["success"]:
                return {"success": False, "device_ip": device_ip, "error": r["error"]}
            if self.is_shutting_down():
                return {"success": False, "device_ip": device_ip, "error": "Cancelled"}
            atomic_write_text(log_path, r["output"])
            return {"success": True, "device_ip": device_ip, "log_path": log_path}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"FileError: {str(e)}"}

    @async_command
    def cleanup_device_logs_async(self, device_ip: str) -> dict:
        r = self._run(self._oneshot_logcat_command(device_ip, "-c"), timeout=30)
        if not r["success"]:
            return {"success": False, "device_ip": device_ip, "error": r["error"]}
        return {"success": True, "device_ip": device_ip, "output": r["output"]}

    # Monkey 测试

    @async_command(long_running=True)
    def run_monkey_test_async(
        self,
        device_ip: str,
        package_name: str,
        params: dict,
        sanitized_name: str,
        save_dir: str,
        index: int,
        callback=None,
        batch_id: str = "",
    ) -> dict:
        def log(msg):
            if not callback:
                return
            try:
                callback(f"[{device_ip}] {msg}")
            except Exception:
                # 进度回调只用于诊断，异常不能破坏测试任务的终态回收。
                return

        start_time = datetime.now()
        result = {
            "device_ip": device_ip,
            "success": False,
            "monkey_log": "",
            "logcat_log": "",
            "duration": "",
            "error": "",
            "index": index,
            "batch_id": batch_id,
            "started_at": start_time.timestamp(),
            "finished_at": start_time.timestamp(),
            "seed": None,
            "cancelled": False,
        }
        monkey_fh = None
        logcat_fh = None
        owned_state = None

        try:
            # Controller 在排队前固定 seed；独立调用沿用旧随机语义并回传实际值。
            seed = params.get("seed")
            if seed is None:
                seed = random.randint(1, 99999)
            result["seed"] = seed
            with self._abort_condition:
                state = self._monkey_batches.get(device_ip)
                if state is None:
                    # 独立同步调用保留旧接口；正常 Controller 已在排队前登记。
                    state = _MonkeyBatchState(batch_id)
                    self._monkey_batches[device_ip] = state
                    self._aborted_devices.discard(device_ip)
                if state.batch_id != batch_id or state.running:
                    raise RuntimeError("Another Monkey batch is already active")
                state.running = True
                owned_state = state
                if state.cancelled or "*" in self._aborted_devices:
                    raise RuntimeError("Aborted by user")
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
                raise ValueError("seed must be an integer between 0 and 2147483647")
            package_name = normalize_android_package(package_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            log_dir = os.path.join(save_dir, f"{sanitized_name}_monkey_{timestamp}")
            monkey_log_path = os.path.join(log_dir, "monkey.txt")
            logcat_log_path = os.path.join(log_dir, "logcat.txt")
            result.update(
                monkey_log=monkey_log_path,
                logcat_log=logcat_log_path,
            )
            self._remember_monkey_archive_result(result)
            os.makedirs(log_dir, exist_ok=True)
            log("Clearing previous device logs...")
            cleared = self._run(self._oneshot_logcat_command(device_ip, "-c"), timeout=30)
            if not cleared["success"]:
                result["error"] = cleared.get("error") or "Failed to clear device logs"
                return result

            log(f"Starting logcat collection -> {logcat_log_path}")
            logcat_fh = open(logcat_log_path, "w", encoding="utf-8")
            self._start_testing_process(
                f"{device_ip}_logcat",
                ["adb", "-s", device_ip, "logcat", "-v", "time"],
                stdout=logcat_fh,
                monkey_batch=(device_ip, batch_id),
            )

            monkey_cmd = [
                "adb",
                "-s",
                device_ip,
                "shell",
                "monkey",
                "-p",
                package_name,
                "-v",
                "--throttle",
                str(params.get("throttle", 300)),
                "--pct-touch",
                str(params.get("touch", 30)),
                "--pct-motion",
                str(params.get("motion", 15)),
                "--pct-trackball",
                str(params.get("trackball", 0)),
                "--pct-nav",
                str(params.get("nav", 20)),
                "--pct-majornav",
                str(params.get("majornav", 10)),
                "--pct-syskeys",
                str(params.get("syskeys", 5)),
                "--pct-appswitch",
                str(params.get("appswitch", 8)),
                "--pct-anyevent",
                str(params.get("anyevent", 10)),
                "--pct-pinchzoom",
                str(params.get("pinch", 2)),
                "-s",
                str(seed),
            ]
            if params.get("ignore_crashes", True):
                monkey_cmd.append("--ignore-crashes")
            if params.get("ignore_timeouts", True):
                monkey_cmd.append("--ignore-timeouts")
            if params.get("ignore_security", True):
                monkey_cmd.append("--ignore-security-exceptions")
            monkey_cmd.append("--kill-process-after-error")
            total_events = params.get("events", 10000)
            monkey_cmd.append(str(total_events))

            log(f"Monkey: {' '.join(monkey_cmd)}")

            monkey_fh = open(monkey_log_path, "w", encoding="utf-8")
            monkey_proc = self._start_testing_process(
                f"{device_ip}_monkey",
                monkey_cmd,
                stdout=monkey_fh,
                monkey_batch=(device_ip, batch_id),
            )

            log("Starting Monkey Test monitoring loop...")
            consecutive_off = 0
            recovery_count = 0
            interval = 60
            probe_failures = 0

            while monkey_proc.poll() is None:
                if self._wait_for_monkey_abort(device_ip, 0):
                    self._procs.stop(f"{device_ip}_monkey")
                    log("Monkey test aborted by user.")
                    result["error"] = "Aborted by user"
                    return result
                probe = self._probe_current_package(device_ip)
                if probe.get("cancelled") or self._wait_for_monkey_abort(device_ip, 0):
                    result["error"] = "Aborted by user"
                    break
                if not probe["success"]:
                    probe_failures += 1
                    failure_kind = "timed out" if probe["timed_out"] else "failed"
                    log(
                        f"Foreground app probe {failure_kind} "
                        f"({probe_failures}/3): {probe['error']}"
                    )
                    if probe_failures >= 3:
                        if probe["timed_out"]:
                            result["error"] = "Device appears disconnected"
                        else:
                            result["error"] = (
                                f"Foreground app probe failed 3 consecutive times: {probe['error']}"
                            )
                        break
                    if self._wait_for_monkey_abort(device_ip, interval):
                        result["error"] = "Aborted by user"
                        break
                    continue

                probe_failures = 0
                current_app = probe["package_name"]
                try:
                    if current_app and current_app != package_name:
                        consecutive_off += 1
                        log(f"App off-target (current={current_app}, streak={consecutive_off})")
                    else:
                        if consecutive_off > 0:
                            log(f"App back on target ({package_name})")
                        consecutive_off = 0

                    # 分层恢复策略在连续两次偏离目标包时触发。
                    if consecutive_off >= 2:
                        recovery_count += 1
                        if recovery_count > 5:
                            log("Max recovery (5) reached, stopping test")
                            monkey_proc.terminate()
                            try:
                                monkey_proc.wait(timeout=5)
                            except Exception:
                                pass
                            result["error"] = "Exceeded max recovery attempts"
                            break

                        if recovery_count <= 3:
                            log(
                                f"Light recovery #{recovery_count}: bringing app back "
                                f"(monkey -p {package_name} 1)"
                            )
                            self._run(
                                [
                                    "adb",
                                    "-s",
                                    device_ip,
                                    "shell",
                                    "monkey",
                                    "-p",
                                    package_name,
                                    "1",
                                ],
                            )
                        else:
                            log(
                                f"Heavy recovery #{recovery_count}: "
                                "killing monkey and restarting..."
                            )
                            try:
                                monkey_proc.terminate()
                                monkey_proc.wait(timeout=5)
                            except Exception:
                                try:
                                    monkey_proc.kill()
                                except Exception:
                                    pass

                            executed = self._count_executed_events(monkey_log_path)
                            remaining = max(1, total_events - executed)
                            log(f"Executed {executed}/{total_events} events, {remaining} remaining")

                            log(f"Force-stopping {package_name}...")
                            self._run(
                                ["adb", "-s", device_ip, "shell", "am", "force-stop", package_name],
                            )
                            if self._wait_for_monkey_abort(device_ip, 1):
                                result["error"] = "Aborted by user"
                                break

                            try:
                                monkey_fh.close()
                            except Exception:
                                pass
                            monkey_fh = open(monkey_log_path, "a", encoding="utf-8")
                            monkey_fh.write(
                                f"\n--- Heavy recovery #{recovery_count} @ {datetime.now()}, "
                                f"{remaining} events ---\n"
                            )
                            monkey_fh.flush()

                            restart_cmd = monkey_cmd.copy()
                            restart_cmd[-1] = str(remaining)
                            for i, arg in enumerate(restart_cmd):
                                if arg == "--pct-appswitch" and i + 1 < len(restart_cmd):
                                    restart_cmd[i + 1] = "0"
                                elif arg == "--pct-syskeys" and i + 1 < len(restart_cmd):
                                    restart_cmd[i + 1] = "2"

                            log(f"Restart monkey: {' '.join(restart_cmd)}")
                            monkey_proc = self._start_testing_process(
                                f"{device_ip}_monkey",
                                restart_cmd,
                                stdout=monkey_fh,
                                monkey_batch=(device_ip, batch_id),
                            )
                            log(f"New monkey started (pid={monkey_proc.pid})")

                        consecutive_off = 0

                    if self._wait_for_monkey_abort(device_ip, interval):
                        result["error"] = "Aborted by user"
                        break
                except subprocess.TimeoutExpired:
                    probe_failures += 1
                    log(f"dumpsys window timed out ({probe_failures}/3)")
                    if probe_failures >= 3:
                        log("Device appears disconnected, stopping monitor")
                        result["error"] = "Device appears disconnected"
                        break
                except Exception as e:
                    log(f"Polling exception: {str(e)}")
                    if self._wait_for_monkey_abort(device_ip, interval):
                        result["error"] = "Aborted by user"
                        break

            if self._wait_for_monkey_abort(device_ip, 0):
                result["error"] = "Aborted by user"
            result["duration"] = str(datetime.now() - start_time)
            return_code = monkey_proc.poll()
            if result["error"]:
                result["success"] = False
                log(f"Monkey test failed for {device_ip}: {result['error']}")
            elif return_code not in (0, None):
                result["success"] = False
                result["error"] = f"Monkey exited with code {return_code}"
                log(result["error"])
            else:
                result["success"] = True
                log(f"Monkey test complete for {device_ip} / ({index})")

        except Exception as e:
            result["error"] = str(e)
            result["duration"] = str(datetime.now() - start_time)
            log(f"Monkey test failed: {e}")

        finally:
            if owned_state is not None:
                # 与停止命令原子排序；旧批次收尾完成之前不能登记新批次。
                with self._process_lifecycle_lock:
                    with self._abort_condition:
                        owns_batch = self._monkey_batches.get(device_ip) is owned_state
                    if owns_batch:
                        self._procs.stop(f"{device_ip}_logcat")
                        self._procs.stop(f"{device_ip}_monkey")
                        with self._abort_condition:
                            self._monkey_batches.pop(device_ip, None)
                            self._aborted_devices.discard(device_ip)
            for fh in (monkey_fh, logcat_fh):
                try:
                    if fh:
                        fh.close()
                except Exception:
                    pass
            result["finished_at"] = time.time()
            result["duration"] = str(datetime.now() - start_time)
            result["cancelled"] = result["error"] == "Aborted by user"
            # 失败或用户停止后仍可能产生有效采集文件，显式标记已存在的附件。
            result["available_artifacts"] = [
                result[key] for key in ("monkey_log", "logcat_log")
                if result.get(key) and os.path.isfile(result[key])
            ]
            result["terminal"] = True
            if owned_state is not None:
                self._remember_monkey_archive_result(result)

        return result

    def _count_executed_events(self, log_path: str) -> int:
        """统计 monkey log 中已执行的 Sending 事件数，用于断点续跑。"""
        try:
            count = 0
            with open(log_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ":Sending" in line:
                        count += 1
            return count
        except (OSError, FileNotFoundError):
            return 0

    @async_command
    def kill_monkey_async(self, device_ip: str, index: int, batch_id: str = "") -> dict:
        try:
            with self._process_lifecycle_lock:
                with self._abort_condition:
                    state = self._monkey_batches.get(device_ip)
                    if batch_id and (state is None or state.batch_id != batch_id):
                        return {
                            "device_ip": device_ip, "index": index, "batch_id": batch_id,
                            "success": True, "message": "Monkey is not running",
                            "already_stopped": True,
                        }
                    if state is not None:
                        state.cancelled = True
                    self._aborted_devices.add(device_ip)
                    self._abort_condition.notify_all()
                    pending = state is not None and not state.running
                if pending:
                    local_code = None
                    r = {"success": True, "output": ""}
                else:
                    # 停止与下一批进程启动共用同一锁，晚到 pkill 不能落到新批次。
                    local_code = self._procs.stop(f"{device_ip}_monkey")
                    r = self._run(
                        [
                            "adb", "-s", device_ip, "shell",
                            "pkill -f com.android.commands.monkey || true",
                        ],
                        timeout=10,
                        device_ip=device_ip,
                    )
            error = (r.get("error") or "").strip()
            already_stopped = local_code is None and not error
            success = r["success"] or already_stopped or (local_code is not None and not error)
            if already_stopped:
                message = "Monkey is not running"
            elif success:
                message = "Monkey process stopped"
            else:
                message = error or "Monkey stop command failed with no error output"
            result = {
                "device_ip": device_ip,
                "index": index,
                "success": success,
                "message": message,
                "already_stopped": already_stopped,
            }
        except Exception as exc:
            result = {
                "device_ip": device_ip,
                "index": index,
                "success": False,
                "message": str(exc),
                "already_stopped": False,
            }
        if batch_id:
            result["batch_id"] = batch_id
        return result

    # Bugreport

    @async_command(long_running=True)
    def capture_bugreport_async(
        self, device_ip: str, save_root: str, index: int, callback=None
    ) -> dict:
        def log(msg):
            if callback:
                callback(f"[{device_ip}] {msg}")

        timestamp = datetime.now().strftime("%H%M%S")
        sanitized = re.sub(r"\W+", "_", device_ip)
        target_dir = os.path.join(save_root, f"{sanitized}_bugreport_{timestamp}")
        os.makedirs(target_dir, exist_ok=True)
        log(f"Created directory: {target_dir}")

        log("Getting Android version...")
        r = self._run(
            ["adb", "-s", device_ip, "shell", "getprop", "ro.build.version.release"],
        )
        version_str = r["output"] if r["success"] else ""
        log(f"Android version: {version_str or 'unknown'}")

        try:
            android_version = tuple(map(int, (version_str or "0").split(".")))
        except ValueError:
            return {
                "device_ip": device_ip,
                "index": index,
                "success": False,
                "message": "Invalid Android version format",
            }

        try:
            if android_version >= (8, 0):
                log("Running: adb bugreport <dir> ... this may take 1-2 minutes")
                bugreport_cmd = ["adb", "-s", device_ip, "bugreport", target_dir]
            else:
                log("Running: adb bugreport <file> ... this may take 1-2 minutes")
                output_file = os.path.join(target_dir, f"bugreport_{device_ip}.txt")
                bugreport_cmd = ["adb", "-s", device_ip, "bugreport", output_file]

            bugreport = self._run(bugreport_cmd, timeout=180)
            if not bugreport["success"]:
                return {
                    "device_ip": device_ip,
                    "index": index,
                    "success": False,
                    "message": f"Bugreport failed: {bugreport.get('error', 'unknown error')}",
                }
            log("Bugreport command completed")
        except Exception as e:
            return {
                "device_ip": device_ip,
                "index": index,
                "success": False,
                "message": f"Bugreport failed: {e}",
            }

        if not self._extract_bugreport_zips(target_dir, log):
            return {
                "device_ip": device_ip,
                "index": index,
                "success": False,
                "message": "Failed to extract bugreport ZIP",
            }

        found_html = self._scan_and_convert_bugreport_txt(target_dir, log)
        if not found_html:
            log("No bugreport text files converted to HTML.")

        return {
            "device_ip": device_ip,
            "index": index,
            "success": True,
            "message": f"Bugreport saved in {target_dir}",
            "bugreport_path": target_dir,
        }

    def _extract_bugreport_zips(self, target_dir: str, log) -> bool:
        zip_files = [f for f in os.listdir(target_dir) if f.endswith(".zip")]
        if not zip_files:
            log("No ZIP found, continuing")
            return True
        try:
            for zip_file in zip_files:
                zip_path = os.path.join(target_dir, zip_file)
                log(f"Extracting ZIP: {zip_file}")
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    safe_extract_zip(zip_ref, target_dir)
            log("Extracted ZIP successfully")
            return True
        except Exception as e:
            log(f"Failed to unzip: {e}")
            return False

    def _scan_and_convert_bugreport_txt(self, target_dir: str, log) -> bool:
        log("Scanning for bugreport text files...")
        found_html = False
        for root, _, files in os.walk(target_dir):
            for f in files:
                if f.startswith("bugreport") and f.endswith(".txt"):
                    txt_path = os.path.join(root, f)
                    log(f"Found bugreport text: {f}")
                    try:
                        self._convert_bugreport_to_html(txt_path, log=log)
                        found_html = True
                    except Exception:
                        continue
        return found_html

    def _convert_bugreport_to_html(self, bugreport_txt_path: str, log=None):
        jar_path = resource_path("resources/chkbugreport-0.5-215.jar")
        if not os.path.isfile(jar_path):
            raise RuntimeError(f"chkbugreport jar not found: {jar_path}")
        if not shutil.which("java"):
            raise RuntimeError("java executable not found in PATH")
        cmd = ["java", "-jar", jar_path, bugreport_txt_path]
        if log:
            log(f"Converting to HTML: {os.path.basename(bugreport_txt_path)}")
        r = CommandRunner.run(cmd, timeout=120)
        if r.success:
            if log:
                log("Bugreport HTML generated successfully.")
        else:
            if log:
                log(f"Conversion failed: {r.error}")
            raise RuntimeError(r.error)

    # ANR 文件拉取

    @async_command(long_running=True)
    def pull_anr_files_async(
        self, device_ip: str, sanitized_name: str, save_dir: str, index: int
    ) -> dict:
        device_anr_dir = os.path.join(save_dir, sanitized_name)
        os.makedirs(device_anr_dir, exist_ok=True)
        r = self._run(
            ["adb", "-s", device_ip, "pull", "/data/anr", device_anr_dir],
            timeout=30,
            device_ip=device_ip,
        )
        if r["success"]:
            return {
                "device_ip": device_ip,
                "success": True,
                "index": index,
                "message": f"ANR files saved to {device_anr_dir}",
                "artifact_path": device_anr_dir,
            }
        return {
            "device_ip": device_ip,
            "success": False,
            "index": index,
            "message": f"Failed to pull ANR files.\n{r['error']}",
        }
