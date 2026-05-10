"""
Testing and diagnostics: monkey test, bugreport, screenshot, logs, ANR pull.

Imports only from adb_model (core) — no circular dependencies.
"""

import os
import re
import subprocess
import time
import zipfile
from datetime import datetime

from .adb_model import ADBModelCore, async_command


class ADBTesting(ADBModelCore):
    """Testing tools: monkey, bugreport, screenshot, log retrieval, ANR pull."""

    # ── Screenshot ────────────────────────────────────────────────────

    @async_command
    def take_screenshot_async(self, device_ip: str, save_path: str) -> dict:
        try:
            temp_path = "/sdcard/screenshot.png"
            self._execute_command(["adb", "-s", device_ip, "shell", "screencap", "-p", temp_path])
            self._execute_command(["adb", "-s", device_ip, "pull", temp_path, save_path])
            self._execute_command(["adb", "-s", device_ip, "shell", "rm", temp_path])
            return {"success": True, "device_ip": device_ip, "screenshot_path": save_path}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Device logs ───────────────────────────────────────────────────

    @async_command
    def retrieve_device_logs_async(self, device_ip: str, log_path: str) -> dict:
        try:
            r = self._exec(["adb", "-s", device_ip, "logcat", "-d"])
            if not r["ok"]:
                return {"success": False, "device_ip": device_ip, "error": r["error"]}
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(r["data"])
            return {"success": True, "device_ip": device_ip, "log_path": log_path}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"FileError: {str(e)}"}

    @async_command
    def cleanup_device_logs_async(self, device_ip: str) -> dict:
        r = self._exec(["adb", "-s", device_ip, "logcat", "-c"])
        if not r["ok"]:
            return {"success": False, "device_ip": device_ip, "error": r["error"]}
        return {"success": True, "device_ip": device_ip, "output": r["data"]}

    # ── Monkey test ───────────────────────────────────────────────────

    @async_command
    def run_monkey_test_async(
        self,
        device_ip: str,
        package_name: str,
        count: str,
        device_type: str,
        sanitized_name: str,
        save_dir: str,
        index: int,
        callback=None,
    ) -> dict:
        def log(msg):
            if callback:
                callback(f"[{device_ip}] {msg}")

        timestamp = datetime.now().strftime("%H%M%S")
        log_dir = os.path.join(save_dir, f"{sanitized_name}_monkey_{timestamp}")
        os.makedirs(log_dir, exist_ok=True)
        monkey_log_path = os.path.join(log_dir, "monkey.txt")
        logcat_log_path = os.path.join(log_dir, "logcat.txt")

        start_time = datetime.now()
        result = {
            "device_ip": device_ip,
            "success": False,
            "monkey_log": monkey_log_path,
            "logcat_log": logcat_log_path,
            "duration": "",
            "error": "",
            "index": index,
        }
        logcat_proc = None

        try:
            log("Clearing previous device logs...")
            subprocess.run(
                ["adb", "-s", device_ip, "logcat", "-c"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            log(f"Starting logcat collection -> {logcat_log_path}")
            logcat_proc = subprocess.Popen(
                ["adb", "-s", device_ip, "logcat", "-v", "time"],
                stdout=open(logcat_log_path, "w", encoding="utf-8"),
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            log(f"Launching Monkey test on {device_type}...")
            throttle = "500" if device_type == "Mobile" else "1000"
            monkey_cmd = [
                "adb",
                "-s",
                device_ip,
                "shell",
                "monkey",
                "-p",
                package_name,
                "-v",
                "-v",
                "-v",
                "--throttle",
                throttle,
                "--ignore-crashes",
                "--ignore-timeouts",
                "--ignore-security-exceptions",
                "--pct-touch",
                "35" if device_type == "Mobile" else "21",
                "--pct-motion",
                "15" if device_type == "Mobile" else "5",
                "--pct-trackball",
                "0",
                "--pct-nav",
                "25" if device_type == "Mobile" else "67",
                "--pct-majornav",
                "10" if device_type == "Mobile" else "5",
                "--pct-syskeys",
                "2" if device_type == "Mobile" else "1",
                "--pct-appswitch",
                "10" if device_type == "Mobile" else "0",
                "--pct-anyevent",
                "3" if device_type == "Mobile" else "1",
                "-s",
                "12345",
                count,
            ]

            monkey_proc = subprocess.Popen(
                monkey_cmd,
                stdout=open(monkey_log_path, "w", encoding="utf-8"),
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            log("Starting Monkey Test monitoring loop...")
            last_switch_time = 0.0
            cooldown, interval = 30, 15

            while monkey_proc.poll() is None:
                try:
                    output = subprocess.check_output(
                        ["adb", "-s", device_ip, "shell", "dumpsys", "window"],
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        text=True,
                    )
                    current_app = ""
                    for line in output.splitlines():
                        if "mCurrentFocus" in line or "mFocusedApp" in line:
                            current_app = line.split()[-1].split("/")[0]
                            break

                    if current_app != package_name and (time.time() - last_switch_time) > cooldown:
                        log("App in background, switching back...")
                        subprocess.run(
                            ["adb", "-s", device_ip, "shell", "am", "force-stop", package_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        subprocess.run(
                            ["adb", "-s", device_ip, "shell", "monkey", "-p", package_name, "1"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        last_switch_time = time.time()
                    time.sleep(interval)
                except Exception as e:
                    log(f"Polling exception: {str(e)}")
                    time.sleep(interval)

            stderr = monkey_proc.stderr.read()
            if stderr:
                result["error"] = stderr.decode(errors="ignore")
            result["success"] = True
            result["duration"] = str(datetime.now() - start_time)
            log(f"Monkey test complete for {device_ip} / ({index})")

        except Exception as e:
            result["error"] = str(e)
            result["duration"] = str(datetime.now() - start_time)
            log(f"Monkey test failed: {e} | Time: {result['duration']}")

        finally:
            try:
                if logcat_proc:
                    logcat_proc.terminate()
                    logcat_proc.wait()
                    log("logcat process terminated.")
            except Exception as e:
                log(f"Failed to terminate logcat process: {e}")

        return result

    @async_command
    def kill_monkey_async(self, device_ip: str, index: int) -> dict:
        result = {"device_ip": device_ip, "index": index, "success": False, "message": ""}
        try:
            cmd = ["adb", "-s", device_ip, "shell", "ps | grep monkey"]
            output = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            ).strip()

            if not output:
                result["message"] = "No monkey process is running on the device"
                return result

            for line in output.splitlines():
                parts = line.split()
                if len(parts) > 1:
                    pid = parts[1]
                    try:
                        kill_cmd = ["adb", "-s", device_ip, "shell", "kill", pid]
                        subprocess.check_output(
                            kill_cmd,
                            stderr=subprocess.STDOUT,
                            text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        result["success"] = True
                        result["message"] = f"Monkey process (PID: {pid}) successfully killed"
                        return result
                    except subprocess.CalledProcessError as e:
                        result["message"] = (
                            f"Failed to kill monkey process (PID: {pid}): " f"{e.output}"
                        )
                        return result
            result["message"] = "Monkey PID not found"
            return result
        except subprocess.CalledProcessError as e:
            result["message"] = f"Error executing 'ps | grep monkey': {e.output}"
            return result

    # ── Bugreport ─────────────────────────────────────────────────────

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
        version_cmd = ["adb", "-s", device_ip, "shell", "getprop", "ro.build.version.release"]
        version_proc = subprocess.run(
            version_cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        version_str = version_proc.stdout.strip()
        log(f"Android version: {version_str or 'unknown'}")

        try:
            android_version = tuple(map(int, version_str.split(".")))
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
                cmd = ["adb", "-s", device_ip, "bugreport", target_dir]
            else:
                log("Running: adb bugreport <file> ... this may take 1-2 minutes")
                output_file = os.path.join(target_dir, f"bugreport_{device_ip}.txt")
                cmd = ["adb", "-s", device_ip, "bugreport", output_file]

            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
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
                    zip_ref.extractall(target_dir)
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
                        self.convert_bugreport_to_html(txt_path, log=log)
                        found_html = True
                    except Exception:
                        continue
        return found_html

    def convert_bugreport_to_html(self, bugreport_txt_path: str, log=None):
        jar_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "resources", "chkbugreport-0.5-215.jar")
        )
        cmd = ["java", "-jar", jar_path, bugreport_txt_path]
        if log:
            log(f"Converting to HTML: {os.path.basename(bugreport_txt_path)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                if log:
                    log("Bugreport HTML generated successfully.")
            else:
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, output=result.stdout, stderr=result.stderr
                )
        except subprocess.CalledProcessError as e:
            if log:
                log(f"Conversion failed: {e.stderr.strip()}")
            raise
        except Exception as e:
            if log:
                log(f"Unexpected error: {str(e)}")
            raise

    # ── ANR pull ──────────────────────────────────────────────────────

    @async_command
    def pull_anr_files_async(
        self, device_ip: str, sanitized_name: str, save_dir: str, index: int
    ) -> dict:
        try:
            device_anr_dir = os.path.join(save_dir, f"{sanitized_name}_anr")
            os.makedirs(device_anr_dir, exist_ok=True)
            pull_command = ["adb", "-s", device_ip, "pull", "/data/anr", device_anr_dir]
            subprocess.check_output(
                pull_command,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return {
                "device_ip": device_ip,
                "success": True,
                "message": f"ANR files saved to {device_anr_dir}",
                "index": index,
            }
        except subprocess.CalledProcessError as e:
            return {
                "device_ip": device_ip,
                "success": False,
                "message": (
                    f"Failed to pull ANR files.\n"
                    f"Command: {' '.join(e.cmd)}\n"
                    f"Return code: {e.returncode}\n"
                    f"Error output:\n{e.output.strip()}"
                ),
                "index": index,
            }
