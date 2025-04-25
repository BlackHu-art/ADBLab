import threading
from PySide6.QtCore import QObject, Signal, QTimer
from models.adb_model import ADBModel
from models.device_store import DeviceStore
from services.log_service import LogService
from utils.yaml_tool import YamlTool

class ADBControllerSignals(QObject):
    """ADB Controller Signal Definitions"""
    devices_updated = Signal(list)  # Device list updated
    device_info_updated = Signal(str, dict)  # Single device info updated (ip, info)
    screenshot_captured = Signal(str, str)  # Screenshot captured (ip, image path)
    logs_retrieved = Signal(str, str)  # Logs retrieved (ip, log content)
    operation_completed = Signal(str, bool, str)  # Operation result (operation name, success, message)

class ADBController:
    """Fully decoupled ADB controller communicating via signals"""
    
    def __init__(self, log_service: LogService):
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self.adb_model = ADBModel()
        self.connected_devices_file = "resources/connected_devices.yaml"
        # 连接ADBModel的信号
        self._pending_operations = {}  # 跟踪进行中的异步操作
        self.adb_model.command_finished.connect(self._handle_async_response)
        
        try:
            DeviceStore.load()
            self.log_service.log("INFO", "DeviceStore loaded successfully")
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()

    # ----- Core Device Operations -----
    def connect_device(self, ip: str):
        """Connect to a device"""
        if not ip:
            self._emit_operation("connect", False, "IP address cannot be empty")
            return
        try:
            devices = ADBModel.get_connected_devices()
            if ip in devices:
                self._emit_operation("connect", False, "{ip} allready connected")
                return
        except Exception:
            return

        try:
            result = ADBModel.connect_device(ip)
            if not result:
                self._emit_operation("connect", False, "No response from ADB")
                return

            if "connected" in result:
                self._save_device_info(ip)
                self.refresh_devices()
                self._emit_operation("connect", True, f"Successfully connected to {ip}")
            elif "already connected" in result:
                self._emit_operation("connect", True, f"{ip} is already connected")
            else:
                self._emit_operation("connect", False, f"Connection failed: {result}")

        except ConnectionRefusedError:
            self._emit_operation("connect", False, f"{ip} refused connection")
        except Exception as e:
            self._emit_operation("connect", False, f"Connection error: {str(e)}")

    def refresh_devices(self):
        """Refresh the list of connected devices"""
        try:
            devices = ADBModel.get_connected_devices()
            self.log_service.log("DEBUG", f"Raw devices from ADB: {devices}")
            
            if not devices:
                self._emit_operation("refresh", True, "No devices currently connected")
                self.signals.devices_updated.emit([])
                return
            
            self._emit_operation("refresh", True, f"Found {len(devices)} connected devices")
            threading.Thread(
                target=self._async_update_devices,
                args=(devices,),
                daemon=True
            ).start()

        except Exception as e:
            self._emit_operation("refresh", False, f"Failed to refresh devices: {str(e)}")
            self.signals.devices_updated.emit([])

    def _async_update_devices(self, devices: list):
        """Asynchronously update all device information"""
        for ip in devices:
            try:
                self._save_device_info(ip)
            except Exception as e:
                self._emit_operation("refresh", False, f"Failed to get info for {ip}: {str(e)}")
        
        self.signals.devices_updated.emit(devices)
    
    def _save_device_info(self, ip: str):
        """Save device information to YAML"""
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
            
            # Update YAML file
            yaml_data = YamlTool.load_yaml(self.connected_devices_file) or {}
            yaml_data.update(device_data)
            YamlTool.write_yaml(self.connected_devices_file, yaml_data)
            
            # Update device store
            DeviceStore.add_device(
                alias=f"device_{ip}",
                ip=ip,
                brand=info.get("Brand", "Unknown"),
                model=info.get("Model", "Unknown"),
                aversion = info.get("Aversion", "Unknown")
                
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
            self._emit_operation("disconnect", False, "Please select at least one device")
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
            self._emit_operation("restart", False, "Please select at least one device")
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
        """Take screenshot of selected devices"""
        if not devices:
            self._emit_operation("screenshot", False, "No devices selected")
            return
            
        for ip in devices:
            try:
                screenshot_path = ADBModel.capture_screenshot(ip)
                self.signals.screenshot_captured.emit(ip, screenshot_path)
                self._emit_operation("screenshot", True, f"Screenshot saved for {ip}")
            except Exception as e:
                self._emit_operation("screenshot", False, f"Failed to capture screenshot for {ip}: {str(e)}")

    def retrieve_device_logs(self, devices: list):
        """Retrieve logs from selected devices"""
        if not devices:
            self._emit_operation("get_logs", False, "No devices selected")
            return
            
        for ip in devices:
            try:
                logs = ADBModel.get_device_logs(ip)
                self.signals.logs_retrieved.emit(ip, logs)
                self._emit_operation("get_logs", True, f"Successfully retrieved logs for {ip}")
            except Exception as e:
                self._emit_operation("get_logs", False, f"Failed to get logs for {ip}: {str(e)}")

    def cleanup_device_logs(self, devices: list):
        """Clean up logs on selected devices"""
        if not devices:
            self._emit_operation("clean_logs", False, "No devices selected")
            return
            
        for ip in devices:
            try:
                ADBModel.cleanup_logs(ip)
                self._emit_operation("clean_logs", True, f"Successfully cleaned logs for {ip}")
            except Exception as e:
                self._emit_operation("clean_logs", False, f"Failed to clean logs for {ip}: {str(e)}")

    # ----- Private Methods -----

    def _emit_operation(self, operation: str, success: bool, message: str):

        level = "INFO" if success else "ERROR"
        self.log_service.log(level, f"[{operation}] {message}")
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
            "disconnect_device": self._process_disconnect_result,
            "get_device_info": self._process_device_info_result,
            "restart_devices": self._process_restart_devices_resoult,
            "restart_adb": self._process_restart_adb_result,
            # 可以继续添加其他操作...
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

        