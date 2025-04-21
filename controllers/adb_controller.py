import json
import threading
from models.adb_model import ADBModel
from models.device_store import DeviceStore
from services.log_service import LogService
from utils.yaml_util import YamlTool


class ADBController:
    def __init__(self, left_panel):
        self.left_panel = left_panel
        self.connected_devices_file = "resources/connected_devices.yaml"
        DeviceStore.load()
        self.left_panel.refresh_device_combobox()
        self.log_service = LogService()

    def on_connect_device(self, event=None):
        # ⛔ 不再使用 currentData，直接读取输入框内容
        ip = self.left_panel.ip_entry.currentText().strip()

        if not ip:
            self.log_service.log("ERROR", "IP address cannot be empty.")
            return

        if ip in self.left_panel.connected_device_cache:
            self.log_service.log("WARNING", f"{ip} is already connected.")
            return

        try:
            result = ADBModel.connect_device(ip)
            if not result:
                self.log_service.log("ERROR", "No response from ADB.")
                return

            if "connected" in result:
                self.log_service.log("WARNING", f"{result}")
                self._save_devices_basic_info(ip)
                self.on_refresh_devices()
            elif "already connected" in result:
                self.log_service.log("INFO", f"{ip} is already connected.")
            else:
                self.log_service.log("ERROR", f"Connection failed: {result}")

        except ConnectionRefusedError:
            self.log_service.log("ERROR", f"{ip} refused connection.")
        except Exception as e:
            self.log_service.log("CRITICAL", f"Connection error: {str(e)}")


    def _save_devices_basic_info(self, ip: str):
        basic_info = ADBModel.get_devices_basic_info(ip)

        device_entry = {
            f"device_{ip}": {
                "ip": ip,
                "Model": basic_info.get("Model", ip),
                "Brand": basic_info.get("Brand", "Unknown"),
                "Android Version": basic_info.get("Android Version", "Unknown"),
                "SDK Version": basic_info.get("SDK Version", "Unknown")
            }
        }

        # 加载并更新 YAML
        yaml_path = self.connected_devices_file
        content = YamlTool.load_yaml(yaml_path)
        content.update(device_entry)

        if not YamlTool.write_yaml(yaml_path, content):
            self._log_safe("ERROR", f"Failed to save device info for {ip}")
            return

        # 更新 DeviceStore 并刷新 ComboBox
        DeviceStore.add_device(
            alias=f"device_{ip}",
            ip=ip,
            brand=basic_info.get("Brand", "Unknown"),
            model=basic_info.get("Model", "Unknown")
        )
        DeviceStore.load()
        self.left_panel.refresh_device_combobox()


    def on_refresh_devices(self, event=None):
        try:
            devices = ADBModel.get_connected_devices()
            if not devices:
                self.log_service.log("WARNING", "No devices connected.")
                return
            else:
                self.log_service.log("INFO", f"{len(devices)} devices connected.")

            # ⏳ 启动后台线程获取并保存设备信息
            thread = threading.Thread(
                target=self._refresh_and_save_devices_async,
                args=(devices,),
                daemon=True
            )
            thread.start()

        except Exception as e:
            self.log_service.log("ERROR", f"Refresh failed: {str(e)}")


    def _refresh_and_save_devices_async(self, device_ips):
        for ip in device_ips:
            try:
                self._save_devices_basic_info(ip)
            except Exception as e:
                self.log_service.log("ERROR", f"[{ip}] fetch failed: {str(e)}")

        # ✅ 刷新 UI 设备列表
        self.left_panel.update_device_list(device_ips)

    # 其余方法保持不变……
    def on_get_device_info(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "Please select at least one device")
            return

        for device in devices:
            try:
                info = ADBModel.get_device_info(device)
                formatted_info = json.dumps(info, indent=4)
                self.log_service.log("INFO", 
                    f"Device info for {device}:\n{formatted_info}")
            except Exception as e:
                self.log_service.log("ERROR", 
                    f"Failed to get info for {device}: {str(e)}")
    
    def on_disconnect_device(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "No device selected")
            return
        for device in devices:
            try:
                result = ADBModel.disconnect_device(device)
                if "disconnected" in result:
                    self.log_service.log("INFO", f"Disconnected {device} successfully")
                    self.left_panel.connected_device_cache.remove(device)
                    self.left_panel.update_device_list()
                else:
                    self.log_service.log("WARNING", f"{device} is not connected")
            except Exception as e:
                self.log_service.log("ERROR", f"Failed to disconnect {device}: {str(e)}")
                continue
    
    def on_restart_devices(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "No devices selected")
            return
        for device in devices:
            try:
                ADBModel.restart_device(device)
                self.log_service.log("INFO", f"{device} restarted")
            except Exception as e:
                self.log_service.log("ERROR", f"Failed to restart {device}: {str(e)}")
                continue
            
    def on_restart_adb(self, event=None):
        try:
            self.log_service.log("INFO", "Restarting ADB")
            result = ADBModel.restart_adb()
            self.log_service.log("INFO", f"ADB restarted {result}")
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to restart ADB: {str(e)}")
            return

    def on_current_activity(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "No device selected")
            return
            
        for device in devices:
            try:
                activity = ADBModel.get_current_activity(device)
                self.log_service.log("INFO", 
                    f"Current activity on {device}:\n{activity}")
            except Exception as e:
                self.log_service.log("ERROR", 
                    f"Failed to get activity for {device}: {str(e)}")

    def on_select_apk(self, event=None):
        try:
            self.log_service.log("DEBUG", "APK selection initiated")
            ADBModel.parse_apk(self.left_panel.main_frame)
        except Exception as e:
            self.log_service.log("ERROR", f"APK selection failed: {str(e)}")

    def on_get_anr_files(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "Select devices first")
            return
            
        for device in devices:
            try:
                threading.Thread(
                    target=ADBModel.get_anr_files,
                    args=(device, self.left_panel.main_frame),
                    daemon=True
                ).start()
                self.log_service.log("INFO", 
                    f"ANR files collection started for {device}")
            except Exception as e:
                self.log_service.log("ERROR", 
                    f"Failed to start ANR collection for {device}: {str(e)}")

    def on_kill_all_apps(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "No devices selected")
            return

        for device in devices:
            try:
                self.log_service.log("DEBUG", 
                    f"Attempting to kill apps on {device}")
                result = ADBModel.kill_all_apps(device)
                
                if "success" in result.lower():
                    self.log_service.log("INFO", 
                        f"Successfully killed apps on {device}")
                else:
                    self.log_service.log("ERROR", 
                        f"Failed to kill apps on {device}: {result}")
            except Exception as e:
                self.log_service.log("CRITICAL", 
                    f"Critical error killing apps on {device}: {str(e)}")

    def on_get_installed_packages(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_service.log("WARNING", "Select devices first")
            return

        for device in devices:
            try:
                self.log_service.log("DEBUG", 
                    f"Fetching packages from {device}")
                packages = ADBModel.get_installed_packages(device)
                
                if packages:
                    self.log_service.log("INFO", 
                        f"Found {len(packages)} packages on {device}")
                    self.log_service.log("DEBUG",  # 详细列表用DEBUG级别
                        f"Package list for {device}:\n" + "\n".join(packages))
                else:
                    self.log_service.log("WARNING", 
                        f"No packages found on {device}")
            except Exception as e:
                self.log_service.log("ERROR", 
                    f"Failed to get packages from {device}: {str(e)}")

    def on_measure_startup_time(self, event=None):
        devices = self.left_panel.selected_devices
        app_package = self.left_panel.main_frame.app_package_input.text().strip()
        
        if not devices:
            self.log_service.log("WARNING", "Device selection required")
            return
        if not app_package:
            self.log_service.log("WARNING", "App package cannot be empty")
            return

        for device in devices:
            try:
                self.log_service.log("INFO", 
                    f"Starting measurement setup for {app_package} on {device}")
                threading.Thread(
                    target=self.measure_startup_time,
                    args=(device, app_package),
                    daemon=True
                ).start()
            except Exception as e:
                self.log_service.log("ERROR", 
                    f"Failed to start measurement thread for {device}: {str(e)}")

