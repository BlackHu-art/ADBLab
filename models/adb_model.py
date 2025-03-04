import subprocess
import time
import os
import zipfile
from utils.adb_utils import execute_adb_command

class ADBModel:
    @staticmethod
    def connect_device(ip_address):
        try:
            output = subprocess.check_output(f"adb connect {ip_address}", shell=True, encoding="utf-8", stderr=subprocess.STDOUT)
            return output.strip()
        except subprocess.CalledProcessError as e:
            return f"Error: {e.output.strip()}"

    @staticmethod
    def get_devices():
        try:
            output = subprocess.check_output("adb devices", shell=True, encoding="utf-8", stderr=subprocess.STDOUT)
            # 忽略第一行，筛选状态为 device 的设备
            devices = [line.split()[0].strip() for line in output.splitlines()[1:] if line.strip().endswith("device")]
            return devices
        except subprocess.CalledProcessError:
            return []
        
    @staticmethod
    def get_device_info(device):
        # 获取设备基本信息，示例：型号、品牌、Android版本、序列号、存储信息等
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Android Version": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
            "Serial Number": ["adb", "-s", device, "shell", "getprop", "ro.serialno"],
            "Storage": ["adb", "-s", device, "shell", "df", "-h", "/data"]
        }
        info = {}
        for key, cmd in commands.items():
            try:
                output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.STDOUT).strip()
                info[key] = output
            except subprocess.CalledProcessError:
                info[key] = "Error fetching info"
        return info
