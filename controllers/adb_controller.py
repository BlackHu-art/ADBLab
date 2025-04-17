import json
import os
import threading
import yaml
from models.adb_model import ADBModel
from models.device_store import DeviceStore


class ADBController:
    def __init__(self, left_panel):
        self.left_panel = left_panel
        self.connected_devices_file = "resources/connected_devices.yaml"
        DeviceStore.load()
        self.left_panel.refresh_device_combobox()

    def on_connect_device(self, event=None):
        # ⛔ 不再使用 currentData，直接读取输入框内容
        ip = self.left_panel.ip_entry.currentText().strip()

        if not ip:
            self.left_panel.main_frame.log_message("ERROR", "IP address cannot be empty.")
            return

        # ✅ 如果你依然希望支持用户从下拉中选数据，你可以用正则提取
        # 或保留 userData 但明确以 currentText 为主（推荐）

        if ip in self.left_panel.connected_device_cache:
            self.left_panel.main_frame.log_message("WARNING", f"{ip} is already connected.")
            return

        try:
            result = ADBModel.connect_device(ip)
            if not result:
                self.left_panel.main_frame.log_message("ERROR", "No response from ADB.")
                return

            if "connected" in result:
                self.left_panel.main_frame.log_message("WARNING", f"{result}")
                self._save_devices_basic_info(ip)
                self.on_refresh_devices()
            elif "already connected" in result:
                self.left_panel.main_frame.log_message("INFO", f"{ip} is already connected.")
            else:
                self.left_panel.main_frame.log_message("ERROR", f"Connection failed: {result}")

        except ConnectionRefusedError:
            self.left_panel.main_frame.log_message("ERROR", f"{ip} refused connection.")
        except Exception as e:
            self.left_panel.main_frame.log_message("CRITICAL", f"Connection error: {str(e)}")


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

        # 更新 YAML 文件
        content = {}
        if os.path.exists(self.connected_devices_file):
            with open(self.connected_devices_file, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}

        content.update(device_entry)
        os.makedirs(os.path.dirname(self.connected_devices_file), exist_ok=True)
        with open(self.connected_devices_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(content, f)

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
                self.left_panel.main_frame.log_message("WARNING", "No devices connected.")
                return
            else:
                self.left_panel.main_frame.log_message("INFO", f"{len(devices)} devices connected.")

            # ⏳ 启动后台线程获取并保存设备信息
            thread = threading.Thread(
                target=self._refresh_and_save_devices_async,
                args=(devices,),
                daemon=True
            )
            thread.start()

        except Exception as e:
            self.left_panel.main_frame.log_message("ERROR", f"Refresh failed: {str(e)}")


    def _refresh_and_save_devices_async(self, device_ips):
        for ip in device_ips:
            try:
                self._save_devices_basic_info(ip)
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", f"[{ip}] fetch failed: {str(e)}")

        # ✅ 刷新 UI 设备列表
        self.left_panel.update_device_list(device_ips)

    # 其余方法保持不变……
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
    
    def on_disconnect_device(self, event=None):
        devices = self.left_panel.selected_devices
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "No device selected")
            return
        for device in devices:
            try:
                result = ADBModel.disconnect_device(device)
                if "disconnected" in result:
                    self.left_panel.main_frame.log_message("INFO", f"Disconnected {device} successfully")
                    self.left_panel.connected_device_cache.remove(device)
                    self.left_panel.update_device_list()
                else:
                    self.left_panel.main_frame.log_message("WARNING", f"{device} is not connected")
            except Exception as e:
                self.left_panel.main_frame.log_message("ERROR", f"Failed to disconnect {device}: {str(e)}")
                continue

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

