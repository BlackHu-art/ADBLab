import os
import yaml
from models.adb_model import ADBModel
from models.device_store import DeviceStore  # 统一设备信息存储

def sanitize_device_name(device_name: str) -> str:
    return "".join([c if c.isalnum() else "_" for c in device_name])

class ADBController:
    def __init__(self, left_panel):
        self.left_panel = left_panel
        self.connected_devices_file = "resources/connected_devices.yaml"

    def on_connect_device(self, event=None):
        ip_address = self.left_panel.ip_address
        if not ip_address:
            self.left_panel.main_frame.log_message("WARNING", "IP address cannot be empty")
            return
        if ip_address in self.left_panel.connected_device_cache:
            self.left_panel.main_frame.log_message("WARNING", f"{ip_address} is already connected")
            return
        try:
            result = ADBModel.connect_device(ip_address)
            if "connected" in result.lower():
                self.left_panel.main_frame.log_message("DEBUG", f"Successfully connected to {ip_address}")
                self._save_connected_device(ip_address)
                self.on_refresh_devices()
            else:
                self.left_panel.main_frame.log_message("ERROR", f"Connection failed: {result}")
        except Exception as e:
            self.left_panel.main_frame.log_message("CRITICAL", f"Connection error: {str(e)}")

    def _save_connected_device(self, ip_address: str):
        sanitized_name = sanitize_device_name(ip_address)
        data = {"alias": sanitized_name, "ip": ip_address}

        # 初始化 YAML 文件结构
        if not os.path.exists(self.connected_devices_file):
            with open(self.connected_devices_file, 'w') as f:
                yaml.safe_dump({"devices": []}, f)

        # 读取并更新 YAML 文件
        with open(self.connected_devices_file, 'r') as f:
            content = yaml.safe_load(f) or {"devices": []}

        devices = content.get("devices", [])
        if not any(d.get("ip") == ip_address for d in devices):
            devices.append(data)
            content["devices"] = devices
            with open(self.connected_devices_file, 'w') as f:
                yaml.safe_dump(content, f)
            self.left_panel.main_frame.log_message("INFO", f"{ip_address} saved to {self.connected_devices_file}")

        # 更新内存中的 DeviceStore 与 UI ComboBox
        DeviceStore.add_device(sanitized_name, ip_address)
        self.left_panel.refresh_device_combobox()

    def on_refresh_devices(self, event=None):
        try:
            devices = ADBModel.get_connected_devices()
            self.left_panel.update_device_list(devices)
            # self.left_panel.update_ip_entry_options(devices)

            if devices:
                self.left_panel.main_frame.log_message("INFO", 
                    f"Found {len(devices)} device(s): {', '.join(devices)}")
            else:
                self.left_panel.main_frame.log_message("WARNING", "No devices detected")
        except Exception as e:
            self.left_panel.main_frame.log_message("ERROR", f"Refresh failed: {str(e)}")

    def on_get_device_info(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Please select at least one device")
            return

        for device in devices:
            try:
                info = ADBModel.get_device_info(device)
                formatted_info = json.dumps(info, indent=4)
                self.left_panel.main_frame.log_message("INFO", 
                    f"Device info for {device}:\n{formatted_info}")
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", 
                    f"Failed to get info for {device}: {str(e)}")

    def on_current_activity(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "No device selected")
            return
            
        for device in devices:
            try:
                activity = ADBModel.get_current_activity(device)
                self.left_panel.main_frame.log_message("INFO", 
                    f"Current activity on {device}:\n{activity}")
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", 
                    f"Failed to get activity for {device}: {str(e)}")

    def on_select_apk(self, event=None):
        try:
            self.left_panel.main_frame.log_message("DEBUG", "APK selection initiated")
            ADBModel.parse_apk(self.left_panel.main_frame)
        except Exception as e:
            self.left_panel.main_frame.log_message("ERROR", f"APK selection failed: {str(e)}")

    def on_get_anr_files(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Select devices first")
            return
            
        for device in devices:
            try:
                threading.Thread(
                    target=ADBModel.get_anr_files,
                    args=(device, self.left_panel.main_frame),
                    daemon=True
                ).start()
                self.left_panel.main_frame.log_message("INFO", 
                    f"ANR files collection started for {device}")
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", 
                    f"Failed to start ANR collection for {device}: {str(e)}")

    def on_kill_all_apps(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "No devices selected")
            return

        for device in devices:
            try:
                self.left_panel.main_frame.log_message("DEBUG", 
                    f"Attempting to kill apps on {device}")
                result = ADBModel.kill_all_apps(device)
                
                if "success" in result.lower():
                    self.left_panel.main_frame.log_message("INFO", 
                        f"Successfully killed apps on {device}")
                else:
                    self.left_panel.main_frame.log_message("ERROR", 
                        f"Failed to kill apps on {device}: {result}")
            except Exception as e:
                self.left_panel.main_frame.log_message("CRITICAL", 
                    f"Critical error killing apps on {device}: {str(e)}")

    def on_get_installed_packages(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Select devices first")
            return

        for device in devices:
            try:
                self.left_panel.main_frame.log_message("DEBUG", 
                    f"Fetching packages from {device}")
                packages = ADBModel.get_installed_packages(device)
                
                if packages:
                    self.left_panel.main_frame.log_message("INFO", 
                        f"Found {len(packages)} packages on {device}")
                    self.left_panel.main_frame.log_message("DEBUG",  # 详细列表用DEBUG级别
                        f"Package list for {device}:\n" + "\n".join(packages))
                else:
                    self.left_panel.main_frame.log_message("WARNING", 
                        f"No packages found on {device}")
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", 
                    f"Failed to get packages from {device}: {str(e)}")

    def on_measure_startup_time(self, event=None):
        devices = self.left_panel.selected_devices
        app_package = self.left_panel.main_frame.app_package_input.text().strip()
        
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Device selection required")
            return
        if not app_package:
            self.left_panel.main_frame.log_message("WARNING", "App package cannot be empty")
            return

        for device in devices:
            try:
                self.left_panel.main_frame.log_message("INFO", 
                    f"Starting measurement setup for {app_package} on {device}")
                threading.Thread(
                    target=self.measure_startup_time,
                    args=(device, app_package),
                    daemon=True
                ).start()
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", 
                    f"Failed to start measurement thread for {device}: {str(e)}")

