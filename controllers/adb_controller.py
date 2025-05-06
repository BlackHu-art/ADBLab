import os
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal, QTimer, QThread, Slot
from PySide6.QtWidgets import QFileDialog, QWidget
from gui.widgets.py_screenshot.screenshot_viewer import ScreenshotViewer
from models.adb_model import ADBModel
from models.device_store import DeviceStore
from common.log_service import LogService
from utils.yaml_tool import YamlTool, YamlPackageCache

class ADBControllerSignals(QObject):
    """ADB Controller Signal Definitions"""
    devices_updated = Signal(list)  # Device list updated
    device_info_updated = Signal(str, dict)  # Single device info updated (ip, info)
    screenshot_captured = Signal(str, str)  # Screenshot captured (ip, image path)
    logs_retrieved = Signal(str, str)  # Logs retrieved (ip, log content)
    operation_completed = Signal(str, bool, str)  # Operation result (operation name, success, message)
    text_input = Signal(str, str)  # (device_ip, input_text)
    current_package_received = Signal(str, str)  # (device_ip, package_name)
    install_apk_result  = Signal(dict)  # 请求选择APK文件
    uninstall_apk_result = Signal(str, str)  # (device_ip, package_name)
    clear_app_data_result = Signal(str, str)

class ADBController:
    """Fully decoupled ADB controller communicating via signals"""
    
    def __init__(self, log_service: LogService):
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self.adb_model = ADBModel()
        self.connected_devices_file = "resources/connected_devices.yaml"
        self.package_info = "resources/package_info.yaml"
        # 连接ADBModel的信号
        self._pending_operations = {}  # 跟踪进行中的异步操作
        self._active_threads = []  # 跟踪所有活动线程
        self.adb_model.command_finished.connect(self._handle_async_response)
        self.last_save_dir = None  # 新增，记录上次保存的文件夹
        self.executor = ThreadPoolExecutor(max_workers=4)  # 最大并发数
        
        try:
            DeviceStore.load()
            self.log_service.log("INFO", "DeviceStore loaded successfully")
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()
    def __del__(self):
        """析构函数，确保所有线程正确停止"""
        self._cleanup_threads()
    
    def _cleanup_threads(self):
        """清理所有活动线程"""
        for thread in self._active_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait()
        self._active_threads.clear()
    
    def _generate_operation_id(self) -> str:
        """生成唯一的操作ID"""
        return str(uuid.uuid4())
    
    def _add_thread(self, thread: QThread):
        """添加线程到跟踪列表"""
        self._active_threads.append(thread)
        thread.finished.connect(lambda: self._remove_thread(thread))

    def _remove_thread(self, thread: QThread):
        """从跟踪列表移除线程"""
        if thread in self._active_threads:
            self._active_threads.remove(thread)
        thread.deleteLater()
    
    # ----- Core Device Operations -----
    def connect_device(self, ip: str):
        """Connect to a device asynchronously"""
        if not ip:
            self._emit_operation("connect", False, "⚠️ IP address cannot be empty")
            return
        
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("connect", ip)
        
        class ConnectThread(QThread):
            def __init__(self, controller, ip):
                super().__init__()
                self.controller = controller
                self.ip = ip
            
            def run(self):
                try:
                    self.controller.adb_model.connect_device_async(self.ip)
                except Exception as e:
                    self.controller._emit_operation("connect", False, f"Connection error: {str(e)}")
        
        thread = ConnectThread(self, ip)
        self._add_thread(thread)
        thread.start()
        
    def _process_connect_device_result(self, result: str):
        ip = None
        for op_id, (op_name, op_ip) in self._pending_operations.items():
            if op_name == "connect":
                ip = op_ip
                break
        
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
        """Asynchronously update all device information"""
        class UpdateThread(QThread):
            def __init__(self, controller, devices):
                super().__init__()
                self.controller = controller
                self.devices = devices
            
            def run(self):
                for ip in self.devices:
                    try:
                        info = ADBModel.get_devices_basic_info(ip)
                        device_data = {
                            f"device_{ip}": {
                                "ip": ip,
                                "Model": info.get("Model", ip),
                                "Brand": info.get("Brand", "Unknown"),
                                "Aversion": info.get("Aversion", "Unknown"),
                            }
                        }
                        
                        yaml_data = YamlTool.load_yaml(self.controller.connected_devices_file) or {}
                        yaml_data.update(device_data)
                        YamlTool.write_yaml(self.controller.connected_devices_file, yaml_data)
                        
                        DeviceStore.add_device(
                            alias=f"device_{ip}",
                            ip=ip,
                            brand=info.get("Brand", "Unknown"),
                            model=info.get("Model", "Unknown"),
                            aversion=info.get("Aversion", "Unknown")
                        )
                        DeviceStore.load()
                        
                    except Exception as e:
                        self.controller._emit_operation("refresh", False, f"Failed to get info for {ip}: {str(e)}")
                
                self.controller.signals.devices_updated.emit(self.devices)
        
        thread = UpdateThread(self, devices)
        self._add_thread(thread)
        thread.start()
    
    def _save_device_info(self, ip: str):
        """Save device information to YAML (同步方法)"""
        try:
            info = ADBModel.get_devices_basic_info(ip)
            device_data = {
                f"device_{ip}": {
                    "ip": ip,
                    "Model": info.get("Model", ip),
                    "Brand": info.get("Brand", "Unknown"),
                    "Aversion": info.get("Aversion", "Unknown"),
                }
            }
            
            yaml_data = YamlTool.load_yaml(self.connected_devices_file) or {}
            yaml_data.update(device_data)
            YamlTool.write_yaml(self.connected_devices_file, yaml_data)
            
            DeviceStore.add_device(
                alias=f"device_{ip}",
                ip=ip,
                brand=info.get("Brand", "Unknown"),
                model=info.get("Model", "Unknown"),
                aversion=info.get("Aversion", "Unknown")
            )
            DeviceStore.load()
            
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to save device info for {ip}: {str(e)}")
            raise

    # ----- Button Functionalities -----
    def get_device_info(self, devices: list):
        """获取设备信息（同步/异步双模式）"""
        if not devices:
            self._emit_operation("get_info", False, "Please select at least one device")
            return
        # 标记当前操作用于信号处理
        self._current_operation = "get_info"
        # 异步获取每个设备的信息
        for ip in devices:
            self.adb_model.get_device_info_async(ip)
    
    def _process_device_info_result(self, result: dict):
        """专属设备信息处理器"""
        self.signals.device_info_updated.emit(result["ip"], result)
        self._emit_operation("get_info", True, f"Obtained {result['ip']} informations")

    def disconnect_devices(self, devices: list):
        """断开设备连接（异步优化版）"""
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
        # 标记当前操作类型
        self._current_operation = "disconnect"
        # 批量发起异步断开请求
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
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return

        self._current_operation = "restart"
        for ip in devices:
            self.adb_model.restart_device_async(ip)
    
    def _process_restart_devices_resoult(self, result: dict):
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
        """重启ADB服务"""
        self._current_operation = "restart_adb"
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
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
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


    def _select_screenshot_directory(self) -> str:
        """弹出选择截图保存目录"""
        return QFileDialog.getExistingDirectory(
            None,
            "Select Screenshot Directory",
            os.path.expanduser("~")
        )

    def _start_screenshot_process(self, device_ip: str, save_dir: str):
        """启动单个设备的截图流程"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_ip = device_ip.replace(":", "_").replace(".", "_")
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
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
            
        save_dir = self._get_or_select_directory()
        
        if not save_dir:
            self._emit_operation("retrieve_device_logs", False, "No directory selected")
            return
            
        for device_ip in devices:
            self._save_single_device_log(device_ip, save_dir)
    
    def _save_single_device_log(self, device_ip: str, save_dir: str):
        """保存单个设备日志"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_ip = device_ip.replace(":", "_")
        log_path = os.path.join(save_dir, f"log_{timestamp}_{sanitized_ip}.txt")
        
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("retrieve_device_logs", device_ip)
        self.adb_model.save_device_log_async(device_ip, log_path)
    
    def _process_retrieve_logs_result(self, result: dict):
        """处理保存日志结果"""
        device_ip = result.get("device_ip")
        
        if result.get("success"):
            # 直接传入完整消息（不再让 _emit_operation 添加额外前缀）
            message = f"Log saved for {device_ip} at {result['log_path']}"
            self._emit_operation("retrieve_device_logs", True, message)
            self.signals.logs_saved.emit(device_ip, result['log_path'])
        else:
            error = result.get("error", "Unknown error")
            # 提取错误消息的最终部分（去掉 "Error:" 等前缀）
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            message = f"Failed to save log for {device_ip}: {error_msg}"
            self._emit_operation("retrieve_device_logs", False, message)

    def cleanup_device_logs(self, devices: list):
        """清除设备日志"""
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
            
        for device_ip in devices:
            operation_id = self._generate_operation_id()
            self._pending_operations[operation_id] = ("cleanup_device_logs", device_ip)
            self.adb_model.clear_device_log_async(device_ip)
    
    def _process_cleanup_logs_result(self, result: dict):
        """处理清除日志结果"""
        device_ip = result.get("device_ip")
        
        if result.get("success"):
            message = f"Log cleared for {device_ip}"
            self._emit_operation("cleanup_device_logs", True, message)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            message = f"Failed to clear log for {device_ip}: {error_msg}"
            self._emit_operation("cleanup_device_logs", False, message)
    
    def input_text(self, devices: list, text: str):
        """向多个设备输入文本"""
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
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
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
        """获取设备当前运行的程序包名"""
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
        """批量安装 APK"""
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return

        apk_path, _ = QFileDialog.getOpenFileName(
            None,
            "Select APK File",
            "",
            "APK Files (*.apk);;All Files (*)"
        )
        if not apk_path:
            self._emit_operation("install", False, "APK selection canceled")
            return

        self.total_devices = len(devices)
        self.finished_devices = 0
        apk_nama = os.path.basename(apk_path)

        for idx, device_ip in enumerate(devices, 1):
            # 提交安装任务
            self.executor.submit(self._install_single_device, idx, device_ip, apk_path, apk_nama)

    def _install_single_device(self, idx: int, device_ip: str, apk_path: str, apk_nama: str):
        """单设备APK安装任务（带设备序号）"""
        try:
                        # 开始前打印提示
            self._emit_operation("install", True, f"Start install ({idx}/{self.total_devices}) {apk_nama} on {device_ip} ...")
            result = self.adb_model.install_apk_async(device_ip, apk_path, apk_nama, idx)
            result.update({
                "apk_name": apk_nama,
                "device_ip": device_ip,
                "index": idx  # 记录当前是第几台设备
            })
            self.signals.install_apk_result.emit(result)

        except Exception as e:
            self.signals.install_apk_result.emit({
                "success": False,
                "apk_name": apk_nama,
                "device_ip": device_ip,
                "index": idx,
                "error": str(e)
            })

    def _process_install_apk_result(self, result: dict):
        """每台设备安装完成后的处理"""
        apk_name = result.get("apk_name")
        device_ip = result.get("device_ip")
        idx = result.get("index", 1)

        if result.get("success"):
            output = result.get("output", "")
            message = f"✅ install success ({idx}/{self.total_devices}) {apk_name} on {device_ip}\nADB output:{output}"
            self._emit_operation("install", True, message)
        else:
            error = result.get("error", "Unknown error")
            message = f"❌ install failed ({idx}/{self.total_devices}) {apk_name} on {device_ip}\n错误信息:{error}"
            self._emit_operation("install", False, message)

        # 更新完成数量
        self.finished_devices += 1
        # 如果全部完成，可以打一个总提示
        if self.finished_devices == self.total_devices:
            self._emit_operation("install", True, "🎯 所有设备安装任务完成")
            
    def uninstall_apk(self, devices: list, package_name: str):
        """批量卸载 APK（结构与安装保持一致）"""
        if not devices:
            self._emit_operation("uninstall", False, "⚠️ No devices selected")
            return

        if not package_name:
            self._emit_operation("uninstall", False, "⚠️ No package name provided")
            return

        self.total_uninstall = len(devices)
        self.finished_uninstall = 0
        self.success_uninstall = 0

        for idx, device_ip in enumerate(devices, 1):
            # 提交异步任务
            self.executor.submit(self._execute_uninstall_task, idx, device_ip, package_name)

    def _execute_uninstall_task(self, idx: int, device_ip: str, package_name: str):
        """单设备卸载任务（带编号）"""
        try:
            # 开始提示
            self._emit_operation("uninstall", True, f"🚀 Start uninstall ({idx}/{self.total_uninstall}) {package_name} on {device_ip} ...")
            result = self.adb_model.uninstall_app_sync(device_ip, package_name, idx)
            result.update({
                "device_ip": device_ip,
                "package_name": package_name,
                "index": idx
            })
            self.signals.uninstall_apk_result.emit(result)
        except Exception as e:
            self.signals.uninstall_apk_result.emit({
                "success": False,
                "device_ip": device_ip,
                "package_name": package_name,
                "output": f"Exception: {str(e)}",
                "index": idx
            })

    def _process_uninstall_apk_result(self, result: dict):
        """处理每台设备的卸载结果"""
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        output = result.get("output", "")

        if result.get("success"):
            output = result.get("output", "")
            message = f"✅ uninstall success ({idx}/{self.total_devices}) {pkg} on {ip}\nADB output:{output}"
            self._emit_operation("install", True, message)
        else:
            error = result.get("error", "Unknown error")
            message = f"❌ uninstall failed ({idx}/{self.total_devices}) {pkg} on {ip}\n错误信息:{error}"
            self._emit_operation("install", False, message)

        # 更新完成数量
        self.finished_devices += 1
        # 如果全部完成，可以打一个总提示
        if self.finished_devices == self.total_devices:
            self._emit_operation("install", True, "🎯 所有设备卸载任务完成")

    def clear_app_data(self, devices: list, package_name: str):
        """批量清除应用数据"""
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("clear_data", False, "⚠️ No package name provided")
            return

        self.total_clear_data = len(devices)
        self.finished_clear_data = 0
        self.success_clear_data = 0

        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.adb_model.clear_app_data_async, device_ip, package_name, idx)

    def _process_clear_app_data_result(self, result: dict):
        """处理清除数据结果"""
        idx = result.get("idx", 1)
        device_ip = result.get("device_ip", "unknown")
        package_name = result.get("package_name", "unknown")
        output = result.get("output", "")
        success = result.get("success", False)

        msg = (
            f"{'✅ Success' if success else '❌ Failed'} "
            f"({idx}/{self.total_clear_data}) clear data for {package_name} on {device_ip}\n"
            f"ADB output:\n{output}"
        )
        self._emit_operation("clear_data", True, msg)

        if success:
            self.success_clear_data += 1
        self.finished_clear_data += 1

        if self.finished_clear_data == self.total_clear_data:
            summary = (
                f"🎯 Clear app data completed\n"
                f"✅ Success: {self.success_clear_data}\n"
                f"❌ Failed: {self.total_clear_data - self.success_clear_data}"
            )
            self._emit_operation("clear_data", True, summary)

        

    # ----- Private Methods -----
    
    def generate_email(self, devices: list):
        if not devices:
            self._emit_operation("generate_email", False, "No devices selected")
            return

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
            "restart_devices": self._process_restart_devices_resoult,
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

        