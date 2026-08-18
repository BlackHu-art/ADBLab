"""提供 Monkey、Bugreport、截图、设备日志和 ANR 拉取等测试诊断能力。

本模块只依赖核心 adb_model，避免模型之间形成循环依赖。
"""

import os
import random
import re
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime

from utils.adb_values import normalize_android_package
from utils.archive import safe_extract_zip
from utils.resource_path import resource_path

from .adb_model import ADBModelCore, async_command
from .base.command_runner import CommandRunner
from .base.focus_detector import detect_current_package
from .base.process_runner import ProcessRunner


class ADBTesting(ADBModelCore):
    """封装 Monkey、Bugreport、截图、日志获取和 ANR 拉取操作。"""

    def __init__(self):
        super().__init__()
        self._aborted_devices = set()
        self._abort_lock = threading.Lock()
        self._abort_condition = threading.Condition(self._abort_lock)
        self._procs = ProcessRunner()

    def shutdown(self):
        """终止 Monkey/logcat 等测试诊断进程，供应用退出时统一调用。"""
        with self._abort_condition:
            self._aborted_devices.add("*")
            self._abort_condition.notify_all()
        self._procs.stop_all()

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

    def _get_current_package(self, device_ip: str) -> str:
        result = detect_current_package(device_ip)
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
        """探测前台包名；超时、断连或解析失败时按失败关闭策略返回。"""
        try:
            package_name = self._get_current_package(device_ip)
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
            timeout=5,
        )
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

    @async_command
    def take_screenshot_async(self, device_ip: str, save_path: str) -> dict:
        direct = CommandRunner.run_to_file(
            ["adb", "-s", device_ip, "exec-out", "screencap", "-p"],
            save_path,
            timeout=30,
        )
        if direct.success and self._is_valid_png(save_path):
            return {"success": True, "device_ip": device_ip, "screenshot_path": save_path}

        temp_path = "/sdcard/screenshot.png"
        r = self._run(["adb", "-s", device_ip, "shell", "screencap", "-p", temp_path])
        if not r["success"]:
            return {"success": False, "device_ip": device_ip, "error": f"screencap: {r['error']}"}
        r = self._run(["adb", "-s", device_ip, "shell", f"test -f {temp_path} && echo ok"])
        if not r["success"] or r.get("output", "").strip() != "ok":
            return {
                "success": False,
                "device_ip": device_ip,
                "error": "screenshot file not found on device after screencap",
            }
        r = self._run(["adb", "-s", device_ip, "pull", temp_path, save_path])
        if not r["success"]:
            return {"success": False, "device_ip": device_ip, "error": f"pull: {r['error']}"}
        self._run(["adb", "-s", device_ip, "shell", "rm", temp_path])
        return {"success": True, "device_ip": device_ip, "screenshot_path": save_path}

    @staticmethod
    def _is_valid_png(path: str) -> bool:
        try:
            with open(path, "rb") as image_file:
                return image_file.read(8) == b"\x89PNG\r\n\x1a\n"
        except OSError:
            return False

    # 设备日志

    @async_command
    def retrieve_device_logs_async(self, device_ip: str, log_path: str) -> dict:
        try:
            r = self._run(["adb", "-s", device_ip, "logcat", "-d"])
            if not r["success"]:
                return {"success": False, "device_ip": device_ip, "error": r["error"]}
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(r["output"])
            return {"success": True, "device_ip": device_ip, "log_path": log_path}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"FileError: {str(e)}"}

    @async_command
    def cleanup_device_logs_async(self, device_ip: str) -> dict:
        r = self._run(["adb", "-s", device_ip, "logcat", "-c"])
        if not r["success"]:
            return {"success": False, "device_ip": device_ip, "error": r["error"]}
        return {"success": True, "device_ip": device_ip, "output": r["output"]}

    # Monkey 测试

    @async_command
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
        }
        monkey_fh = None
        logcat_fh = None

        try:
            package_name = normalize_android_package(package_name)
            timestamp = datetime.now().strftime("%H%M%S")
            log_dir = os.path.join(save_dir, f"{sanitized_name}_monkey_{timestamp}")
            monkey_log_path = os.path.join(log_dir, "monkey.txt")
            logcat_log_path = os.path.join(log_dir, "logcat.txt")
            result.update(
                monkey_log=monkey_log_path,
                logcat_log=logcat_log_path,
            )
            os.makedirs(log_dir, exist_ok=True)
            with self._abort_condition:
                self._aborted_devices.discard(device_ip)

            log("Clearing previous device logs...")
            self._run(["adb", "-s", device_ip, "logcat", "-c"])

            log(f"Starting logcat collection -> {logcat_log_path}")
            logcat_fh = open(logcat_log_path, "w", encoding="utf-8")
            self._procs.start(
                f"{device_ip}_logcat",
                ["adb", "-s", device_ip, "logcat", "-v", "time"],
                stdout=logcat_fh,
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
                str(random.randint(1, 99999)),
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
            monkey_proc = self._procs.start(
                f"{device_ip}_monkey",
                monkey_cmd,
                stdout=monkey_fh,
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
                            monkey_proc.wait(timeout=5)
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
                            monkey_proc = self._procs.start(
                                f"{device_ip}_monkey",
                                restart_cmd,
                                stdout=monkey_fh,
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
            with self._abort_condition:
                self._aborted_devices.discard(device_ip)
            self._procs.stop(f"{device_ip}_logcat")
            self._procs.stop(f"{device_ip}_monkey")
            for fh in (monkey_fh, logcat_fh):
                try:
                    if fh:
                        fh.close()
                except Exception:
                    pass

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
        with self._abort_condition:
            self._aborted_devices.add(device_ip)
            self._abort_condition.notify_all()
        try:
            local_code = self._procs.stop(f"{device_ip}_monkey")
            r = self._run(
                [
                    "adb",
                    "-s",
                    device_ip,
                    "shell",
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

    @async_command
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

    @async_command
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
            }
        return {
            "device_ip": device_ip,
            "success": False,
            "index": index,
            "message": f"Failed to pull ANR files.\n{r['error']}",
        }
