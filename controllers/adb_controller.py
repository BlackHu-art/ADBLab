import os
import re
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QTimer, Slot, QThreadPool
from PySide6.QtWidgets import QFileDialog
from common.mail.email_task import GetRandomEmailTask

from gui.widgets.py_panel.adb_contral_signals import ADBControllerSignals
from gui.widgets.py_screenshot.screenshot_viewer import ScreenshotViewer
from models.adb_model import ADBModel
from models.device_store import DeviceStore
from common.log_service import LogLevel, LogService
from utils.batch_tracker import BatchOperationTracker


class ADBController:
    """Fully decoupled ADB controller communicating via signals"""
    
    def __init__(self, log_service: LogService):
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self.adb_model = ADBModel()
        self.connected_devices_file = "resources/connected_devices.yaml"
        self.package_info = "resources/package_info.yaml"
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_operations = {}
        self.adb_model.command_finished.connect(self._handle_async_response)
        self.last_save_dir = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._batch_trackers = {}

        try:
            DeviceStore.load()
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()

    def __del__(self):
        self.executor.shutdown(wait=False)

    def _generate_operation_id(self) -> str:
        return str(uuid.uuid4())
    
    # ----- Core Device Operations -----
    def connect_device(self, ip: str):
        if not ip:
            self._emit_operation("connect", False, "⚠️ IP address cannot be empty")
            return

        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("connect", ip)
        self.adb_model.connect_device_async(ip)
        
    def _process_connect_device_result(self, result: str):
        ip = None
        found_key = None
        for key, (op_name, op_ip) in self._pending_operations.items():
            if op_name == "connect":
                ip = op_ip
                found_key = key
                break
        if found_key:
            del self._pending_operations[found_key]

        if not ip:
            self._emit_operation("connect", False, "⚠️ Unknown device connection")
            return
            
        if "connected" in result:
            self._save_device_info(ip)
            self.refresh_devices()
            self._emit_operation("connect", True, f"Successfully connected to {ip}")
        elif "already connected" in result:
            self._emit_operation("connect", True, f"{ip} is already connected")
        else:
            self._emit_operation("connect", False, f"Connection failed: {result}")
    
    def _process_device_list(self, devices: list):
        self._emit_operation("refresh", True, f"Found {len(devices)} connected devices")
        self._async_update_devices(devices)

    def refresh_devices(self):
        """Refresh the list of connected devices asynchronously"""
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("refresh", None)
        
        try:
            self.adb_model.get_connected_devices_async()
        except Exception as e:
            self._emit_operation("refresh", False, f"Failed to refresh devices: {str(e)}")
            self.signals.devices_updated.emit([])

    def _async_update_devices(self, devices: list):
        def _update():
            for ip in devices:
                try:
                    info = ADBModel.get_devices_basic_info(ip)
                    DeviceStore.add_device(
                        alias=f"device_{ip}",
                        ip=ip,
                        brand=info.get("Brand", "Unknown"),
                        model=info.get("Model", "Unknown"),
                        aversion=info.get("Aversion", "Unknown")
                    )
                except Exception as e:
                    self._emit_operation("refresh", False, f"Failed to get info for {ip}: {str(e)}")
            self.signals.devices_updated.emit(devices)

        self.executor.submit(_update)
    
    def _save_device_info(self, ip: str):
        try:
            info = ADBModel.get_devices_basic_info(ip)
            DeviceStore.add_device(
                alias=f"device_{ip}",
                ip=ip,
                brand=info.get("Brand", "Unknown"),
                model=info.get("Model", "Unknown"),
                aversion=info.get("Aversion", "Unknown")
            )
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to save device info for {ip}: {str(e)}")
            raise

    # ----- Button Functionalities -----
    def get_device_info(self, devices: list):
        """获取设备信息（同步/异步双模式）"""
        if not devices:
            self._emit_operation("get_info", False, "Please select at least one device")
            return
        for ip in devices:
            self.adb_model.get_device_info_async(ip)
    
    def _process_device_info_result(self, result: dict):
        """优化后的设备信息处理器"""
        device_ip = result.get("ip", "Unknown")
        # self.signals.device_info_updated.emit(ip, result)

        log = self.log_service.log
        log(LogLevel.INFO, f"📱 Device Info - {device_ip}")
        log(LogLevel.INFO, f"  🧭 Model            : {result.get('Model', '-')}")
        log(LogLevel.INFO, f"  🏷️ Brand            : {result.get('Brand', '-')}")
        log(LogLevel.INFO, f"  🤖 Android Version  : {result.get('Android Version', '-')}")
        log(LogLevel.INFO, f"  🧪 SDK Version      : {result.get('SDK Version', '-')}")
        log(LogLevel.INFO, f"  🧬 CPU Architecture : {result.get('CPU Architecture', '-')}")
        log(LogLevel.INFO, f"  🔧 Hardware         : {result.get('Hardware', '-')}")
        log(LogLevel.INFO, f"  🖼️ Resolution       : {result.get('Resolution', '-')}".replace("Physical size: ", ""))
        log(LogLevel.INFO, f"  🧮 Density          : {result.get('Density', '-')}".replace("Physical density: ", ""))
        log(LogLevel.INFO, f"  🌐 Timezone         : {result.get('Timezone', '-')}")
        log(LogLevel.INFO, f"  🆔 Serial Number    : {result.get('Serial Number', '-')}")
        log(LogLevel.INFO, f"  💾 Total Memory     : {result.get('Total Memory', '-')}")
        log(LogLevel.INFO, f"  📉 Available Memory : {result.get('Available Memory', '-')}")
        
        log(LogLevel.INFO, f"  📂 Storage          :")
        for line in result.get("Storage", "").splitlines():
            log(LogLevel.INFO, f"    {line}")

        log(LogLevel.INFO, f"  📡 MAC / IP Info    :")
        for line in result.get("Mac", "").splitlines():
            log(LogLevel.INFO, f"    {line}")
        log(LogLevel.INFO, f"  ✅ complete\n")


    def disconnect_devices(self, devices: list):
        """断开设备连接（异步优化版）"""
        if not devices:
            self._emit_operation("disconnect", False, "⚠️ No devices selected")
            return

        for ip in devices:
            self.adb_model.disconnect_device_async(ip)
    
    def _process_disconnect_result(self, result: dict):
        """专属断开连接处理器"""
        ip = result["ip"]
        if result.get("success"):
            self.refresh_devices()
            self._emit_operation("disconnect", True, f"Successfully disconnected {ip}")
        else:
            self._emit_operation(
                "disconnect", 
                False, 
                f"Disconnect failed: {result.get('error', 'unknown error')}"
            )

    def restart_devices(self, devices: list):
        """重启设备（异步优化版）"""
        if not devices:
            self._emit_operation("restart", False, "⚠️ No devices selected")
            return

        for ip in devices:
            self.adb_model.restart_device_async(ip)
    
    def _process_restart_devices_result(self, result: dict):
        """健壮的重启结果处理"""
        ip = result.get("ip", "unknown device")
        
        if result.get("success"):
            # 延迟10秒后刷新（等待设备重启完成）
            QTimer.singleShot(10_000, lambda: (
                self.refresh_devices(),
                self._emit_operation("restart", True, f"{ip} Restart completed, device list refreshed")
            ))
            self._emit_operation("restart", True, f"{ip} Restarting in progress...")
        else:
            self._emit_operation("restart", False, f"{ip} Restart failed: {result.get('error', 'unknown device')}")

    def restart_adb(self):
        self.adb_model.restart_adb_async()
    
    def _process_restart_adb_result(self, result: dict):
        """ADB重启结果处理"""
        if result.get("success"):
            # 延迟3秒后刷新（等待ADB服务稳定）
            QTimer.singleShot(3000, self.refresh_devices)  # 非阻塞延迟,但是会导致主界面卡顿一下
            self._emit_operation("restart_adb", True, f"ADB service has been restarted: {result.get('raw_output', '')}")
        else:
            self._emit_operation("restart_adb", False, f"ADB restart failed: {result.get('error', 'unknown error')}")

    def take_screenshot(self, devices: list):
        """触发截图流程"""
        if not devices:
            self._emit_operation("screenshot", False, "⚠️ No devices selected")
            return

        screenshot_dir = self._get_or_select_directory()
        if not screenshot_dir:
            self._emit_operation("screenshot", False, "No directory selected")
            return

        for device_ip in devices:
            if device_ip:
                self._start_screenshot_process(device_ip, screenshot_dir)

    def _get_or_select_directory(self) -> str:
        """如果已有保存目录，直接用；否则弹窗选择"""
        if self.last_save_dir and os.path.exists(self.last_save_dir):
            return self.last_save_dir
        
        # 第一次弹出选择框
        default_path = os.path.join(os.path.expanduser("~"), "Pictures")  # 默认打开“图片”文件夹
        screenshot_dir = QFileDialog.getExistingDirectory(
            None,
            "Select Screenshot Directory",
            default_path
        )
        if screenshot_dir:
            self.last_save_dir = screenshot_dir  # 保存用户选的路径
        return screenshot_dir


    def _start_screenshot_process(self, device_ip: str, save_dir: str):
        """启动单个设备的截图流程"""
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r'\W+', '_', device_ip)
        filename = f"screenshot_{timestamp}_{sanitized_ip}.png"
        save_path = os.path.join(save_dir, filename)

        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("screenshot", device_ip)

        self.adb_model.take_screenshot_async(device_ip, save_path)

    def _process_screenshot_result(self, result: dict):
        """处理截图结果"""
        device_ip = result.get("device_ip", "")

        if result.get("success"):
            path = result["screenshot_path"]
            self.signals.screenshot_captured.emit(device_ip, path)
            self._emit_operation("screenshot", True, f"Screenshot saved to {path}")
            QTimer.singleShot(0, lambda: self._show_screenshot_viewer(path))
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation("screenshot", False, f"Failed to capture screenshot on {device_ip}: {error}")

    def _show_screenshot_viewer(self, image_path: str):
        """显示截图查看窗口"""
        viewer = ScreenshotViewer(image_path)
        viewer.exec()

    def retrieve_device_logs(self, devices: list):
        """保存设备日志到文件"""
        if not devices:
            self._emit_operation("retrieve_device_logs", False, "⚠️ No devices selected")
            return

        save_dir = self._get_or_select_directory()
        
        if not save_dir:
            self._emit_operation("retrieve_device_logs", False, "No directory selected")
            return
            
        for device_ip in devices:
            self._save_single_device_log(device_ip, save_dir)
    
    def _save_single_device_log(self, device_ip: str, save_dir: str):
        """保存单个设备日志"""
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r'\W+', '_', device_ip)
        log_path = os.path.join(save_dir, f"log_{timestamp}_{sanitized_ip}.txt")
        
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("retrieve_device_logs", device_ip)
        self.adb_model.retrieve_device_logs_async(device_ip, log_path)
    
    def _process_retrieve_logs_result(self, result: dict):
        """处理保存日志结果"""
        device_ip = result.get("device_ip")
        log_path = result.get("log_path")
        
        if result.get("success"):
            # 直接传入完整消息（不再让 _emit_operation 添加额外前缀）
            self._emit_operation("retrieve_device_logs", True, f"✅ Log saved for {device_ip} at {log_path}")
            self.signals.logs_retrieved.emit(device_ip, log_path)
        else:
            error = result.get("error", "Unknown error")
            # 提取错误消息的最终部分（去掉 "Error:" 等前缀）
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            message = f"Failed to save log for {device_ip}: {error_msg}"
            self._emit_operation("retrieve_device_logs", False, message)

    def cleanup_device_logs(self, devices: list):
        """清除设备日志"""
        if not devices:
            self._emit_operation("cleanup_device_logs", False, "⚠️ No devices selected")
            return

        for device_ip in devices:
            operation_id = self._generate_operation_id()
            self._pending_operations[operation_id] = ("cleanup_device_logs", device_ip)
            self.adb_model.cleanup_device_logs_async(device_ip)
    
    def _process_cleanup_logs_result(self, result: dict):
        """处理清除日志结果"""
        device_ip = result.get("device_ip")
        
        if result.get("success"):
            message = f"✅ Log cleared for {device_ip}"
            self._emit_operation("cleanup_device_logs", True, message)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            message = f"Failed to clear log for {device_ip}: {error_msg}"
            self._emit_operation("cleanup_device_logs", False, message)
    
    def input_text(self, devices: list, text: str):
        if not devices:
            self._emit_operation("input_text", False, "⚠️ No devices selected")
            return

        if not text.strip():
            self._emit_operation("input_text", False, "⚠️ Input text cannot be empty")
            return
            
        for device_ip in devices:
            self._send_text_to_device(device_ip, text)
    
    def _send_text_to_device(self, device_ip: str, text: str):
        """向单个设备发送文本"""
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("input_text", device_ip)
        self.adb_model.input_text_async(device_ip, text)

    def _process_input_text_result(self, result: dict):
        """处理文本输入结果"""
        device_ip = result.get("device_ip")
        text = result.get("text", "")
        
        if result.get("success"):
            message = f"Text '{text}' input on {device_ip}"
            self._emit_operation("input_text", True, message)
            self.signals.text_input.emit(device_ip, text)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            message = f"Failed to input text on {device_ip}: {error_msg}"
            self._emit_operation("input_text", False, message)
    
    def get_current_package(self, devices: list):
        if not devices:
            self._emit_operation("get_package", False, "⚠️ No devices selected")
            return
        for device_ip in devices:
            self.executor.submit(
                self._get_single_device_package, 
                device_ip
            )
    
    def _get_single_device_package(self, device_ip: str):
        """单个设备获取方法"""
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("get_package", device_ip)
        self.adb_model.get_current_package_async(device_ip)
            
    def _process_get_package_result(self, result: dict):
        """处理获取包名结果"""
        device_ip = result.get("device_ip")
        
        if result.get("success"):
            package_name = result["package_name"]
            self._emit_operation(
                "get_package",
                True,
                f"Current package on {device_ip}: {package_name}"
            )
            # 发射带设备IP和包名的信号
            self.signals.current_package_received.emit(device_ip, package_name)
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation(
                "get_package",
                False,
                f"Failed to get package on {device_ip}: {error}"
            )
    
    def install_apk(self, devices: list):
        if not devices:
            self._emit_operation("install", False, "⚠️ No devices selected")
            return

        apk_path, _ = QFileDialog.getOpenFileName(
            None, "Select APK File", "", "APK Files (*.apk);;All Files (*)"
        )
        if not apk_path:
            self._emit_operation("install", False, "APK selection canceled")
            return

        apk_name = os.path.basename(apk_path)
        self._batch_trackers["install"] = BatchOperationTracker(
            len(devices), "Install App", self._emit_operation
        )

        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self._install_single_device, idx, device_ip, apk_path, apk_name)

    def _install_single_device(self, idx: int, device_ip: str, apk_path: str, apk_name: str):
        try:
            tracker = self._batch_trackers.get("install")
            total = tracker.total if tracker else "?"
            self._emit_operation("install", True, f"Start install ({idx}/{total}) {apk_name} on {device_ip} ...")
            result = self.adb_model.install_apk_async(device_ip, apk_path, apk_name, idx)
            result.update({"apk_name": apk_name, "device_ip": device_ip, "index": idx})
            self.signals.install_apk_result.emit(result)
        except Exception as e:
            self.signals.install_apk_result.emit({
                "success": False, "apk_name": apk_name, "device_ip": device_ip,
                "index": idx, "error": str(e)
            })

    def _process_install_apk_result(self, result: dict):
        apk_name = result.get("apk_name")
        device_ip = result.get("device_ip")
        idx = result.get("index", 1)
        success = result.get("success")
        tracker = self._batch_trackers.get("install")
        progress = tracker.record(success) if tracker else ""

        if success:
            message = f"✅ install success {progress} {apk_name} on {device_ip}\nADB output:{result.get('output', '')}"
            self._emit_operation("install", True, message)
        else:
            message = f"❌ install failed {progress} {apk_name} on {device_ip}\n错误信息:{result.get('error', 'Unknown error')}"
            self._emit_operation("install", False, message)
            
    def uninstall_apk(self, devices: list, package_name: str):
        if not devices:
            self._emit_operation("uninstall", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("uninstall", False, "⚠️ No package name provided")
            return

        self._batch_trackers["uninstall"] = BatchOperationTracker(
            len(devices), "Uninstall App", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self._execute_uninstall_task, idx, device_ip, package_name)

    def _execute_uninstall_task(self, idx: int, device_ip: str, package_name: str):
        try:
            tracker = self._batch_trackers.get("uninstall")
            total = tracker.total if tracker else "?"
            self._emit_operation("uninstall", True, f"🚀 Start uninstall ({idx}/{total}) {package_name} on {device_ip} ...")
            result = self.adb_model.uninstall_app_sync(device_ip, package_name, idx)
            result.update({"device_ip": device_ip, "package_name": package_name, "index": idx})
            self.signals.uninstall_apk_result.emit(result)
        except Exception as e:
            self.signals.uninstall_apk_result.emit({
                "success": False, "device_ip": device_ip,
                "package_name": package_name, "output": f"Exception: {str(e)}", "index": idx
            })

    def _process_uninstall_apk_result(self, result: dict):
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        tracker = self._batch_trackers.get("uninstall")
        progress = tracker.record(success) if tracker else ""

        if success:
            message = f"✅ uninstall success {progress} {pkg} on {ip}\nADB output:{result.get('output', '')}"
            self._emit_operation("uninstall", True, message)
        else:
            message = f"❌ uninstall failed {progress} {pkg} on {ip}\n错误信息:{result.get('output', '')}"
            self._emit_operation("uninstall", False, message)

    def clear_app_data(self, devices: list, package_name: str):
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("clear_data", False, "⚠️ No package name provided")
            return

        self._batch_trackers["clear_data"] = BatchOperationTracker(
            len(devices), "Clear App Data", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.adb_model.clear_app_data_async, device_ip, package_name, idx)

    def _process_clear_app_data_result(self, result: dict):
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        tracker = self._batch_trackers.get("clear_data")
        progress = tracker.record(success) if tracker else ""

        if success:
            message = f"✅ clear data success {progress} {pkg} on {ip}\nADB output:{result.get('output', '')}"
            self._emit_operation("clear_data", True, message)
        else:
            message = f"❌ clear data failed {progress} {pkg} on {ip}\n错误信息:{result.get('output', '')}"
            self._emit_operation("clear_data", False, message)
            
    def restart_app(self, devices: list, package_name: str):
        if not devices:
            self._emit_operation("restart_app", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("restart_app", False, "⚠️ No package name provided")
            return

        self._batch_trackers["restart_app"] = BatchOperationTracker(
            len(devices), "Restart App", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.adb_model.restart_app_async, device_ip, package_name, idx)

    def _process_restart_app_result(self, result: dict):
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        output = result.get("output", "").strip()
        success = result.get("success")
        tracker = self._batch_trackers.get("restart_app")
        progress = tracker.record(success) if tracker else ""

        if success:
            msg = (
                f"✅ Restart Success {progress}\n"
                f"   📦 Package : {pkg}\n"
                f"   🌐 Device  : {ip}\n"
                f"   📤 Output  :\n{self._indent_output(output)}"
            )
            self._emit_operation("restart_app", True, msg)
        else:
            msg = (
                f"❌ Restart Failed {progress}\n"
                f"   📦 Package : {pkg}\n"
                f"   🌐 Device  : {ip}\n"
                f"   ⚠️ Error   :\n{self._indent_output(output)}"
            )
            self._emit_operation("restart_app", False, msg)

    def _indent_output(self, text: str, prefix: str = "     ") -> str:
        """为多行输出添加缩进美化"""
        return "\n".join(f"{prefix}{line}" for line in text.splitlines() if line.strip())


    def get_current_activity(self, devices: list[str]):
        if not devices:
            self._emit_operation("current_activity", False, "⚠️ No device selected")
            return

        self._batch_trackers["current_activity"] = BatchOperationTracker(
            len(devices), "Activity Info", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.adb_model.get_current_activity_async, device_ip, idx)

    def _process_get_current_activity_result(self, result: dict):
        device = result.get("device_ip", "unknown")
        idx = result.get("index", 0)
        success = result.get("success", False)
        focus = result.get("current_focus", "").strip()
        resumed = result.get("resumed_activity", "").strip()
        error = result.get("error", "").strip()
        tracker = self._batch_trackers.get("current_activity")
        progress = tracker.record(success) if tracker else ""

        if success:
            msg_lines = [f"📱 ({idx}) {device} {progress} - Activity Info"]
            if focus:
                msg_lines.append(f"   🔍 Current Focus   :\n{self._indent_output(focus)}")
            else:
                msg_lines.append(f"   ⚠️  No mCurrentFocus found")
            if resumed:
                msg_lines.append(f"   🎯 Resumed Activity:\n{self._indent_output(resumed)}")
            else:
                msg_lines.append(f"   ⚠️  No mResumedActivity found")
            self._emit_operation("current_activity", True, "\n".join(msg_lines))
        else:
            msg = f"❌ Failed to get activity on ({idx}) {device} {progress}\n{self._indent_output(error)}"
            self._emit_operation("current_activity", False, msg)

    def parse_apk_info(self):
        """弹出系统文件选择对话框并解析 APK"""
        apk_path, _ = QFileDialog.getOpenFileName(
            None,
            "Select APK File",
            "",
            "APK Files (*.apk);;All Files (*)"
        )

        if not apk_path:
            self._emit_operation("apk_info", False, "⚠️ APK file selection cancelled")
            return

        if not apk_path.endswith(".apk"):
            self._emit_operation("apk_info", False, f"❌ Invalid APK file selected: {apk_path}")
            return

        self._emit_operation("apk_info", True, f"📦 Selected APK: {apk_path}")
        self.executor.submit(self.adb_model.parse_apk_info_async, apk_path)

    def _process_parse_apk_info_result(self, result: dict):
        """处理 APK 解析结果并提取关键字段"""
        apk_path = result.get("apk_path", "unknown")

        if result.get("success"):
            raw_output = result.get("output", "")
            try:
                # 正则提取核心字段
                package_name = re.search(r"package: name='(.*?)'", raw_output)
                version_code = re.search(r"versionCode='(.*?)'", raw_output)
                version_name = re.search(r"versionName='(.*?)'", raw_output)
                min_sdk = re.search(r"sdkVersion:'(.*?)'", raw_output)
                target_sdk = re.search(r"targetSdkVersion:'(.*?)'", raw_output)
                compile_sdk = re.search(r"compileSdkVersion='(.*?)'", raw_output)
                build_version = re.search(r"platformBuildVersionName='(.*?)'", raw_output)

                label_match = re.search(r"application-label(?:-[\w\-]+)?:'(.*?)'", raw_output)
                app_label = label_match.group(1) if label_match else "N/A"

                icon_match = re.search(r"application: label='.*?' icon='(.*?)'", raw_output)
                icon_path = icon_match.group(1) if icon_match else "N/A"

                permissions = re.findall(r"uses-permission: name='(.*?)'", raw_output)
                features = re.findall(r"uses-feature(?:-not-required)?: name='(.*?)'", raw_output)
                native_code = re.findall(r"native-code: '(.*?)'", raw_output)

                # 格式化输出
                formatted = f"""
    🔹 应用名称: {app_label}
    📦 包名: {package_name.group(1) if package_name else 'N/A'}
    🔢 版本号: {version_name.group(1) if version_name else 'N/A'} (Code: {version_code.group(1) if version_code else 'N/A'})
    🎯 SDK版本: min={min_sdk.group(1) if min_sdk else 'N/A'}, target={target_sdk.group(1) if target_sdk else 'N/A'}, compile={compile_sdk.group(1) if compile_sdk else 'N/A'}
    🛠️ 构建版本: {build_version.group(1) if build_version else 'N/A'}
    🖼️ 应用图标: {icon_path}
    🔐 权限数: {len(permissions)} 项
    ⚙️ 特性声明: {", ".join(features) if features else "None"}
    🧬 支持架构: {", ".join(native_code) if native_code else "未声明"}
    """

                # 可选附加调试信息（开发时开启）
                # formatted += f"\n--- 原始输出 ---\n{raw_output}"

                self._emit_operation("apk_info", True, formatted)

            except Exception as e:
                self._emit_operation("apk_info", False, f"⚠️ APK Field parsing exception: {apk_path}\nError: {str(e)}")

        else:
            error = result.get("error", "Unknown error")
            self._emit_operation("apk_info", False, f"❌ APK Analysis failed: {apk_path}\nError: {error}")

    def kill_monkey(self, devices: list):
        if not devices:
            self._emit_operation("kill_monkey", False, "⚠️ No devices selected")
            return

        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.adb_model.kill_monkey_async, device_ip, idx)

    def _process_kill_monkey_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")

        if result.get("success"):
            self._emit_operation("kill_monkey", True, f"✅ {idx}. Monkey process killed on {device_ip}")
        else:
            self._emit_operation("kill_monkey", False, f"❌ {idx}. Failed to kill monkey process on {device_ip}:\nError: {result['message']}")

    def list_installed_packages(self, devices: list[str]):
        if not devices:
            self._emit_operation("installed_packages", False, "⚠️ No devices selected")
            return
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.adb_model.list_installed_packages_async, device_ip, idx)

    def _process_list_installed_packages_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")

        if result.get("success"):
            packages = result.get("packages", [])
            formatted = "\n".join(f"{i+1}. {pkg}" for i, pkg in enumerate(packages))
            msg = f"📦 {idx}. Installed packages on {device_ip}:\n{formatted or '(None found)'}"
            self._emit_operation("installed_packages", True, msg)
        else:
            msg = result.get("message", "Unknown error")
            self._emit_operation("installed_packages", False, f"❌ {idx}. Failed to get packages from {device_ip}:\n{msg}")

    def capture_bugreport(self, devices: list):
        if not devices:
            self._emit_operation("bugreport", False, "⚠️ No devices selected.")
            return
        save_dir = QFileDialog.getExistingDirectory(None, "Select directory to save ANR files")
        log = self.log_service.log
        for idx, device in enumerate(devices, 1):
            self.executor.submit(
                self.adb_model.capture_bugreport_async,
                device,
                save_dir,
                idx,
                callback=lambda msg: log(LogLevel.INFO, msg)  # ✅ 这里是传入一个真正的函数
            )

    def _process_capture_bugreport_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        success = result.get("success", False)
        message = result.get("message", "")
        
        if success:
            bug_path = result.get("bugreport_path")
            self._emit_operation("bugreport", True, f"✅ {idx}. Bugreport saved from {device_ip}:\n{bug_path}")
        else:
            self._emit_operation("bugreport", False, f"❌ {idx}. Failed on {device_ip}:\n{message}")


    def pull_anr_files(self, devices: list[str]):
        """拉取设备上的 ANR 文件，弹出保存路径选择框"""
        if not devices:
            self._emit_operation("pull_anr", False, "⚠️ No devices selected")
            return

        # 选择保存目录
        save_dir = QFileDialog.getExistingDirectory(None, "Select directory to save ANR files")
        if not save_dir:
            self._emit_operation("pull_anr", False, "⚠️ No target directory selected")
            return

        timestamp = datetime.now().strftime("%H%M%S")
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r'\W+', '_', device_ip)
            self.executor.submit(
                self.adb_model.pull_anr_files_async,
                device_ip,
                f"{sanitized_name}_anr_{timestamp}",
                save_dir,
                idx
            )

    def _process_pull_anr_result(self, result: dict):
        device_ip = result.get("device_ip", "unknown")
        idx = result.get("index", "?")

        if result.get("success"):
            self._emit_operation("pull_anr", True, f"✅ {idx}. Pulled ANR files from {device_ip}:\n{result['message']}")
        else:
            self._emit_operation("pull_anr", False, f"❌ {idx}. Failed to pull ANR from {device_ip}:\n{result['message']}")

    def run_monkey_test(self, devices: list, device_type: str, package_name: str, count: str):
        """执行 Monkey 测试任务调度"""
        # 参数校验
        if not devices:
            return self._emit_operation("monkey", False, "⚠️ No devices selected")
        if not device_type:
            return self._emit_operation("monkey", False, "⚠️ No device type selected")
        if not package_name:
            return self._emit_operation("monkey", False, "⚠️ No package name provided")
        if not count:
            return self._emit_operation("monkey", False, "⚠️ No monkey count provided")

        # 获取保存目录
        save_dir = QFileDialog.getExistingDirectory(None, "Select directory to save Monkey logs")
        if not save_dir:
            return self._emit_operation("monkey", False, "⚠️ No target directory selected")

        log = self.log_service.log
        log(LogLevel.INFO, f"📦 Starting Monkey tests on {len(devices)} devices...")
        log(LogLevel.INFO, f"📁 Log save directory: {save_dir}")

        # 提交任务
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r'\W+', '_', device_ip)
            self.executor.submit(
                self.adb_model.run_monkey_test_async,
                device_ip,
                package_name,
                count,
                device_type,
                sanitized_name,
                save_dir,
                idx,
                callback=lambda msg: self.log_service.log(LogLevel.INFO, msg)
            )

    def _process_run_monkey_test_result(self, result: dict):
        """处理单个 Monkey 测试结果（优化版）"""
        device_ip = result.get("device_ip", "unknown")
        duration = result.get("duration", "N/A")
        monkey_log = result.get("monkey_log", "")
        logcat_log = result.get("logcat_log", "")
        error = result.get("error", "None")

        if result.get("success"):
            message = (
                "\n╔═══════════════════════════════════════════════════════════════════════════\n"
                f"║ ✅ Monkey 测试报告 - 设备: {device_ip}\n"
                "╠═══════════════════════════════════════════════════════════════════════════\n"
                f"║ ⏱️ 执行时长: {duration}\n"
                f"║ 📄 Monkey 日志: {monkey_log}\n"
                f"║ 📄 Logcat 日志: {logcat_log}\n"
                "╚═══════════════════════════════════════════════════════════════════════════"
            )
        else:
            message = (
                "\n╔═══════════════════════════════════════════════════════════════════════════\n"
                f"║ ❌ Monkey 测试失败 - 设备: {device_ip}\n"
                "╠═══════════════════════════════════════════════════════════════════════════\n"
                f"║ ⏱️ 执行时长: {duration}\n"
                f"║ 💥 错误详情: {error[:200]}{'...' if len(error)>200 else ''}\n"
                f"║ 🔍 详细日志: {monkey_log}\n"
                "╚═══════════════════════════════════════════════════════════════════════════"
            )

        return self._emit_operation("monkey", result.get("success"), message)

    def get_random_email_and_code(self):
        task = GetRandomEmailTask()

        # 转发信号给 UI（或主 controller）
        task.signals.log_signal.connect(self.log_service.log)
        task.signals.email_updated.connect(self.signals.email_updated)
        task.signals.vercode_updated.connect(self.signals.vercode_updated)

        self.thread_pool.start(task)




    # ----- Private Methods -----

    @Slot(str, bool, str)
    def _emit_operation(self, operation: str, success: bool, message: str):
        """确保信号在主线程中发射"""
        level = "INFO" if success else "ERROR"
        if not message.strip():
            return  # 防止输出空内容日志
        self.log_service.log(level, f"{message}")
        self.signals.operation_completed.emit(operation, success, message)
    
    def _handle_async_response(self, method_name: str, result):

        # 提取基础操作类型（去掉_async后缀）
        op_type = method_name.replace("_async", "")
        
        # 统一错误处理
        if isinstance(result, str) and result.startswith("AsyncError:"):
            error_msg = result[11:]
            self.log_service.log("ERROR", f"[{op_type}] {error_msg}")
            self._emit_operation(op_type, False, error_msg)
            return
        
        # 设备列表处理
        if op_type == "get_connected_devices":
            if isinstance(result, list):
                self._process_device_list(result)
            else:
                self._emit_operation(op_type, False, "Invalid device list format")
            return
            
        # 操作处理器映射表（扩展版）
        handler_map = {
            "connect_device": self._process_connect_device_result,
            "disconnect_device": self._process_disconnect_result,
            "get_device_info": self._process_device_info_result,
            "restart_devices": self._process_restart_devices_result,
            "restart_adb": self._process_restart_adb_result,
            "take_screenshot": self._process_screenshot_result,
            "retrieve_device_logs": self._process_retrieve_logs_result,
            "cleanup_device_logs": self._process_cleanup_logs_result,
            "input_text": self._process_input_text_result,
            # 可以继续添加其他操作...
            "get_current_package": self._process_get_package_result,
            "install_apk": self._process_install_apk_result,
            "uninstall_apk": self._process_uninstall_apk_result,
            "clear_app_data": self._process_clear_app_data_result,
            "restart_app": self._process_restart_app_result,
            "get_current_activity": self._process_get_current_activity_result,
            "parse_apk_info": self._process_parse_apk_info_result,
            "run_monkey_test": self._process_run_monkey_test_result,
            "kill_monkey": self._process_kill_monkey_result,
            "list_installed_packages": self._process_list_installed_packages_result,
            "capture_bugreport": self._process_capture_bugreport_result,
            "pull_anr_files": self._process_pull_anr_result,

        }
        
        # 获取对应的处理器
        handler = handler_map.get(op_type)
        
        if handler:
            try:
                handler(result)
            except Exception as e:
                self.log_service.log("ERROR", f"[{op_type}] Handler error: {str(e)}")
                self._emit_operation(op_type, False, f"处理失败: {str(e)}")
        else:
            self._default_async_handler(op_type, result)

    def _default_async_handler(self, op_type: str, result):

        if isinstance(result, dict):
            # 如果有IP字段，尝试更新设备信息
            if 'ip' in result:
                self.signals.device_info_updated.emit(result['ip'], result)
            # 如果有成功标志，发射操作完成信号
            if result.get('success', False):
                self._emit_operation(op_type, True, f"{op_type} completed")
            else:
                error_msg = result.get('error', 'Unknown error')
                self._emit_operation(op_type, False, error_msg)
        else:
            # 对于其他类型的成功结果
            self._emit_operation(op_type, True, f"{op_type} completed")

        