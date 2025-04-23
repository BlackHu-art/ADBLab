import json
import threading
from PySide6.QtCore import QObject, Signal
from models.adb_model import ADBModel
from models.device_store import DeviceStore
from services.log_service import LogService
from utils.yaml_util import YamlTool

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
        self.connected_devices_file = "resources/connected_devices.yaml"
        
        try:
            DeviceStore.load()
            self.log_service.log("INFO", "DeviceStore loaded successfully")
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()
        
        # Connect log service
        # self.signals.operation_completed.connect(self._log_operation_result)
    
    # ----- Core Device Operations -----
    def connect_device(self, ip: str):
        """Connect to a device"""
        if not ip:
            self._emit_operation("connect", False, "IP address cannot be empty")
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

    # ----- Button Functionalities -----
    def get_device_info(self, devices: list):
        """Get detailed info for selected devices"""
        if not devices:
            self._emit_operation("get_info", False, "Please select at least one device")
            return

        for ip in devices:
            try:
                info = ADBModel.get_device_info(ip)
                self.signals.device_info_updated.emit(ip, info)
                self._emit_operation("get_info", True, f"Successfully retrieved info for {ip}")
            except Exception as e:
                self._emit_operation("get_info", False, f"Failed to get info for {ip}: {str(e)}")

    def disconnect_devices(self, devices: list):
        """Disconnect selected devices"""
        if not devices:
            self._emit_operation("disconnect", False, "No devices selected")
            return
            
        for ip in devices:
            try:
                result = ADBModel.disconnect_device(ip)
                if "disconnected" in result:
                    self._emit_operation("disconnect", True, f"Successfully disconnected {ip}")
                else:
                    self._emit_operation("disconnect", False, f"{ip} is not connected")
            except Exception as e:
                self._emit_operation("disconnect", False, f"Failed to disconnect {ip}: {str(e)}")

    def restart_devices(self, devices: list):
        """Restart selected devices"""
        if not devices:
            self._emit_operation("restart", False, "No devices selected")
            return
            
        for ip in devices:
            try:
                ADBModel.restart_device(ip)
                self._emit_operation("restart", True, f"Restarting device {ip}...")
            except Exception as e:
                self._emit_operation("restart", False, f"Failed to restart {ip}: {str(e)}")

    def restart_adb(self):
        """Restart ADB service"""
        try:
            result = ADBModel.restart_adb()
            self._emit_operation("restart_adb", True, f"ADB restarted: {result}")
        except Exception as e:
            self._emit_operation("restart_adb", False, f"Failed to restart ADB: {str(e)}")

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
    def _save_device_info(self, ip: str):
        """Save device information to YAML"""
        try:
            info = ADBModel.get_devices_basic_info(ip)
            device_data = {
                f"device_{ip}": {
                    "ip": ip,
                    "Model": info.get("Model", ip),
                    "Brand": info.get("Brand", "Unknown"),
                    "Android Version": info.get("Android Version", "Unknown"),
                    "SDK Version": info.get("SDK Version", "Unknown")
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
                model=info.get("Model", "Unknown")
            )
            DeviceStore.load()
            
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to save device info for {ip}: {str(e)}")
            raise

    def _emit_operation(self, operation: str, success: bool, message: str):

        level = "INFO" if success else "ERROR"
        self.log_service.log(level, f"[{operation}] {message}")
        self.signals.operation_completed.emit(operation, success, message)
        