# adb_controller.py
import json
import threading
from models.adb_model import ADBModel


class ADBController:
    def __init__(self, left_panel):
        # 保存 LeftPanel 引用以便调用界面更新函数
        self.left_panel = left_panel

    def on_connect_device(self, event=None):
        ip_address = self.left_panel.get_ip_entry().currentText().strip()
        if not ip_address:
            self.left_panel.main_frame.log_message("WARNING", "No IP Address entered")
            return
        result = ADBModel.connect_device(ip_address)
        if "connected" in result.lower():
            self.left_panel.main_frame.log_message("INFO", f"Connected to {ip_address}")
            self.on_refresh_devices(event)
        else:
            self.left_panel.main_frame.log_message("ERROR", f"Unable to connect: {result}")

    def on_refresh_devices(self, event=None):
        devices = ADBModel.get_devices()
        listbox_devices = self.left_panel.get_listbox_devices()
        if devices:
            listbox_devices.clear()
            listbox_devices.addItems(devices)
            self.left_panel.main_frame.log_message("INFO", f"Devices: {', '.join(devices)}")
        else:
            listbox_devices.clear()
            self.left_panel.main_frame.log_message("WARNING", "No devices connected.")

    def on_get_device_info(self, event=None):
        try:
            devices = self.left_panel.get_selected_devices()
            if not devices:
                self.left_panel.main_frame.log_message("INFO", "Please select a device!")
                return

            for device in devices:
                try:
                    info = ADBModel.get_device_info(device)
                    formatted_info = json.dumps(info, indent=4)
                    self.left_panel.main_frame.log_message("INFO", f"Device Info for {device}:\n{formatted_info}")
                except Exception as e:
                    self.left_panel.main_frame.log_message("ERROR", f"Failed to get info for {device}: {e}")
        except Exception as e:
            self.left_panel.main_frame.log_message("ERROR", f"An error occurred: {e}")

    def on_current_activity(self, event=None):
        devices = self.left_panel.get_selected_devices()
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Please select a device!")
            return
        for device in devices:
            activity = ADBModel.get_current_activity(device)
            self.left_panel.main_frame.log_message("INFO", f"Current activity on {device}:\n{activity}")

    def on_select_apk(self, event=None):
        # 选择APK文件并解析信息
        self.left_panel.main_frame.log_message("INFO", "Select APK button pressed")
        ADBModel.parse_apk(self.left_panel.main_frame)

    def on_get_anr_files(self, event=None):
        devices = self.left_panel.get_selected_devices()
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "No device selected")
            return
        for device in devices:
            threading.Thread(target=ADBModel.get_anr_files, args=(device, self.left_panel.main_frame), daemon=True).start()

    def on_kill_all_apps(self, event=None):
        devices = self.left_panel.get_selected_devices()
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Please select at least one device.")
            return
        for device in devices:
            result = ADBModel.kill_all_apps(device)
            self.left_panel.main_frame.log_message("INFO", f"Device {device}: {result}")

    def on_get_installed_packages(self, event=None):
        devices = self.left_panel.get_selected_devices()
        if not devices:
            self.left_panel.main_frame.log_message("WARNING", "Please select at least one device.")
            return
        for device in devices:
            packages = ADBModel.get_installed_packages(device)
            self.left_panel.main_frame.log_message("INFO", f"Installed packages on {device}:\n" + "\n".join(packages))

    def on_measure_startup_time(self, event=None):
        devices = self.left_panel.get_selected_devices()
        app_package = self.left_panel.main_frame.app_package_input.text().strip()
        if not devices or not app_package:
            self.left_panel.main_frame.log_message("WARNING", "Select a device and enter an app package!")
            return
        for device in devices:
            threading.Thread(target=self.measure_startup_time, args=(device, app_package), daemon=True).start()

    def measure_startup_time(self, device, app_package):
        self.left_panel.main_frame.log_message("INFO", f"Measuring startup time for {app_package} on {device}.")
        # 获取主活动（自动获取）
        main_activity = ADBModel.get_main_activity(device, app_package)
        if not main_activity:
            self.left_panel.main_frame.log_message("WARNING", f"Unable to retrieve main activity for {app_package} on {device}.")
            return
        cold_times, hot_times = ADBModel.measure_startup_time(device, app_package, main_activity, iterations=20)
        if cold_times and hot_times:
            avg_cold = sum(cold_times) / len(cold_times)
            avg_hot = sum(hot_times) / len(hot_times)
            self.left_panel.main_frame.log_message("INFO", f"{device} - {app_package}: Average Cold Start: {avg_cold:.2f}s, Average Hot Start: {avg_hot:.2f}s")
        else:
            self.left_panel.main_frame.log_message("WARNING", f"Failed to measure startup time for {device}.")