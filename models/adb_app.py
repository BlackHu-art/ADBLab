"""提供应用安装、卸载、数据清理、重启和包信息查询。

本模块只依赖核心 adb_model，避免模型之间形成循环依赖。
"""

import os
import re
import shlex
import shutil

from adblab.application.cancellation import CancellationError, CancellationToken
from core.exec import CommandRunner
from utils.adb_values import normalize_android_package

from .adb_model import ADBModelCore, async_command
from .base.focus_detector import detect_current_package


class ADBApp(ADBModelCore):
    """封装应用安装、卸载、清理、重启、列表和查询等生命周期操作。"""

    def get_current_package(self, device_ip: str) -> dict:
        return detect_current_package(device_ip)

    @async_command
    def get_current_package_async(self, device_ip: str) -> dict:
        return self.get_current_package(device_ip)

    @async_command
    def prepare_monkey_targets_async(
        self, devices: list[str], package_name: str, request_id: str,
        cancellation: CancellationToken,
    ) -> dict:
        """后台核对完整目标快照；准备阶段只查询，不启动应用或 Monkey。

        每条查询有有限超时，取消和 model 关闭在命令前后检查；异常保留请求身份，
        让界面总能结束对应准备态。不同设备可以安装同包的不同版本。
        """
        targets = list(dict.fromkeys(device for device in devices if device))
        result = {
            "request_id": request_id, "devices": targets, "package_name": package_name,
            "success": False, "packages": [],
        }

        def check_cancelled() -> None:
            cancellation.raise_if_cancelled()
            if self.is_shutting_down():
                raise CancellationError("Model is shutting down")

        class FocusRunner:
            def run(self, command: list[str], timeout: int = 5):
                check_cancelled()
                response = CommandRunner.run(command, timeout=timeout)
                check_cancelled()
                return response

        try:
            check_cancelled()
            if not targets:
                raise ValueError("请先选择测试设备")
            try:
                package = normalize_android_package(package_name) if package_name.strip() else ""
            except ValueError as exc:
                raise ValueError("应用包名格式无效，请输入完整包名后重试") from exc
            if not package:
                foreground = []
                for index, device in enumerate(targets, 1):
                    detected = detect_current_package(device, FocusRunner())
                    if not detected.get("success"):
                        raise ValueError(f"第 {index} 台设备无法获取前台应用，请输入测试包名后重试")
                    foreground.append(normalize_android_package(detected.get("package_name", "")))
                if len(set(foreground)) != 1:
                    raise ValueError("所选设备的前台应用不一致，请输入要测试的包名")
                package = foreground[0]
            result["package_name"] = package
            packages = []
            for index, device in enumerate(targets, 1):
                check_cancelled()
                installed = self._run(
                    ["adb", "-s", device, "shell", "pm", "path", shlex.quote(package)],
                    timeout=5,
                )
                check_cancelled()
                if not installed.get("success"):
                    raise ValueError(f"第 {index} 台设备无法查询已安装应用，请检查连接与调试授权")
                if not any(
                    line.startswith("package:") and line.removeprefix("package:").strip()
                    for line in installed["output"].splitlines()
                ):
                    raise ValueError(f"第 {index} 台设备未安装目标应用，请先安装后重试")
                details = self._run(
                    ["adb", "-s", device, "shell", "dumpsys", "package", shlex.quote(package)],
                    timeout=5,
                )
                check_cancelled()
                if not details.get("success"):
                    raise ValueError(f"第 {index} 台设备无法获取测试包信息，请重试")
                output = details.get("output", "")
                if not re.search(r"Package\s+\[" + re.escape(package) + r"\]", output):
                    raise ValueError(f"第 {index} 台设备返回的包信息不匹配，请重新获取")
                info = {"device_ip": device, "package_name": package}
                for key, pattern in (
                    ("version_name", r"versionName=(\S+)"),
                    ("version_code", r"versionCode=(\d+)"),
                    ("target_sdk", r"targetSdk=(\d+)"),
                ):
                    match = re.search(pattern, output)
                    info[key] = match.group(1) if match else ""
                packages.append(info)
            check_cancelled()
            result.update(success=True, packages=packages)
        except CancellationError:
            result.update(cancelled=True, error="已取消获取测试包信息")
        except ValueError as exc:
            result["error"] = str(exc)
        except Exception as exc:
            # 异步边界必须保留 request_id；否则通用装饰器的错误字典无法解除本次准备态。
            result.update(error="获取测试包信息失败，请检查连接后重试", error_detail=str(exc))
        return result

    def install_apk(
        self,
        device_ip: str,
        apk_path: str,
        apk_name: str,
        idx: int,
        operation: str = "install",
    ) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "install", "-r", apk_path],
            timeout=120,
            device_ip=device_ip,
            apk_path=apk_path,
            index=idx,
            apk_name=apk_name,
            operation=operation,
        )

    @async_command(long_running=True)
    def install_apk_async(
        self,
        device_ip: str,
        apk_path: str,
        apk_name: str,
        idx: int,
        operation: str = "install",
    ):
        return self.install_apk(device_ip, apk_path, apk_name, idx, operation=operation)

    def uninstall_app(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "uninstall", package_name],
            timeout=30,
            device_ip=device_ip,
            package_name=package_name,
            index=idx,
        )

    @async_command
    def uninstall_app_async(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self.uninstall_app(device_ip, package_name, idx)

    @async_command
    def clear_app_data_async(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "clear", shlex.quote(package_name)],
            timeout=30,
            device_ip=device_ip,
            package_name=package_name,
            index=idx,
        )

    @async_command
    def restart_app_async(self, device_ip: str, package_name: str, index: int) -> dict:
        """先停止再启动应用；停止失败时保留错误并禁止后续启动。"""
        r1 = self._run(
            ["adb", "-s", device_ip, "shell", "am", "force-stop", shlex.quote(package_name)],
            device_ip=device_ip,
        )
        if not r1["success"]:
            error = r1.get("error") or "Failed to stop application"
            return {
                "success": False,
                "device_ip": device_ip,
                "package_name": package_name,
                "index": index,
                "output": error,
                "error": error,
            }
        r2 = self._run(
            [
                "adb",
                "-s",
                device_ip,
                "shell",
                "monkey",
                "-p",
                shlex.quote(package_name),
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            device_ip=device_ip,
        )
        result = {
            "success": r2["success"],
            "device_ip": device_ip,
            "package_name": package_name,
            "index": index,
            "output": (
                f"{r1.get('output', r1.get('error', ''))}\n"
                f"{r2.get('output', r2.get('error', ''))}"
            ),
        }
        if not r2["success"]:
            result["error"] = r2.get("error") or "Failed to launch application"
        return result

    @async_command
    def get_current_activity_async(self, device_ip: str, index: int = 0) -> dict:
        r1 = self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "window"],
            timeout=10,
            device_ip=device_ip,
        )
        r2 = self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "activity", "activities"],
            timeout=10,
            device_ip=device_ip,
        )
        current_focus = ""
        resumed_activity = ""
        if r1["success"]:
            for line in r1["output"].splitlines():
                if "mCurrentFocus" in line:
                    current_focus = line.strip()
                    break
        if r2["success"]:
            for line in r2["output"].splitlines():
                if "mResumedActivity" in line:
                    resumed_activity = line.strip()
                    break
        success = r1["success"] and r2["success"]
        error = ""
        if not r1["success"]:
            error = r1.get("error", "dumpsys window failed")
        elif not r2["success"]:
            error = r2.get("error", "dumpsys activity failed")
        result = {
            "success": success,
            "device_ip": device_ip,
            "index": index,
            "current_focus": current_focus,
            "resumed_activity": resumed_activity,
        }
        if error:
            result["error"] = error
        return result

    @async_command
    def parse_apk_info_async(self, apk_path: str) -> dict:
        if not os.path.isfile(apk_path):
            return {
                "success": False,
                "error": f"APK file not found: {apk_path}",
                "apk_path": apk_path,
            }
        aapt = shutil.which("aapt")
        if not aapt:
            return {
                "success": False,
                "error": "aapt executable not found in PATH",
                "apk_path": apk_path,
            }
        return self._run([aapt, "dump", "badging", apk_path], timeout=15, apk_path=apk_path)

    @async_command
    def input_text_async(self, device_ip: str, text: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "text", shlex.quote(text)],
            device_ip=device_ip,
            text=text,
        )

    def list_installed_packages(self, device_ip: str, index: int) -> dict:
        r = self._run(
            ["adb", "-s", device_ip, "shell", "pm", "list", "packages"], device_ip=device_ip
        )
        if not r["success"]:
            return {"device_ip": device_ip, "success": False, "message": r["error"], "index": index}
        packages = [
            line.replace("package:", "").strip()
            for line in r["output"].splitlines()
            if line.startswith("package:")
        ]
        return {"device_ip": device_ip, "success": True, "packages": packages, "index": index}

    @async_command
    def list_installed_packages_async(self, device_ip: str, index: int) -> dict:
        return self.list_installed_packages(device_ip, index)
