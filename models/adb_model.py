import subprocess
import time
import os
import zipfile
from utils.adb_utils import execute_adb_command

class ADBModel:
    @staticmethod
    def connect_device(ip_address: str) -> str:
        """返回标准化连接状态信息，不抛出异常"""
        try:
            result = subprocess.run(
                ["adb", "connect", ip_address],
                capture_output=True,
                text=True,
                timeout=10  # 增加超时控制
            )
            
            # 解析adb返回信息
            if "connected" in result.stdout.lower():
                return f"Success: {result.stdout.strip()}"
            elif "already connected" in result.stdout.lower():
                return "Already connected"
            elif result.returncode != 0:
                return f"Error[{result.returncode}]: {result.stderr.strip() or result.stdout.strip()}"
            else:
                return "Unknown connection status"
                
        except subprocess.TimeoutExpired:
            return "Timeout: Connection attempt exceeded 10 seconds"
        except Exception as e:
            return f"SystemError: {str(e)}"
        
    @staticmethod
    def get_connected_devices():
        """返回所有通过 adb 连接的设备"""
        result = os.popen("adb devices").read()
        lines = result.strip().splitlines()[1:]  # 跳过第一行 'List of devices attached'
        devices = []
        for line in lines:
            if "device" in line:
                device_id = line.split("\t")[0]
                devices.append(device_id)
        return devices

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
            "SDK Version": ["adb", "-s", device, "shell", "getprop", "ro.build.version.sdk"],
            "CPU Architecture": ["adb", "-s", device, "shell", "getprop", "ro.product.cpu.abi"],
            "Hardware": ["adb", "-s", device, "shell", "getprop", "ro.hardware"],
            "Storage": ["adb", "-s", device, "shell", "df", "-h", "/data"],
            "Total Memory": ["adb", "-s", device, "shell", "cat", "/proc/meminfo", "|", "grep", "MemTotal"],
            "Available Memory": ["adb", "-s", device, "shell", "cat", "/proc/meminfo", "|", "grep",
                                 "MemAvailable"],
            "Resolution": ["adb", "-s", device, "shell", "wm", "size"],
            "Density": ["adb", "-s", device, "shell", "wm", "density"],
            "Timezone": ["adb", "-s", device, "shell", "getprop", "persist.sys.timezone"],
            "Mac": ["adb", "-s", device, "shell", "ip", "addr", "show", "wlan0"],
        }
        device_info = {}
        for key, cmd in commands.items():
            try:                
                output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.STDOUT).strip()
                device_info[key] = output
            except subprocess.CalledProcessError:
                device_info[key] = "Error fetching info"
        return device_info
    
    @staticmethod
    def get_devices_basic_info(device):
        # 获取设备基本信息，示例：型号、品牌、Android版本、序列号、存储信息等
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Android Version": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
            "SDK Version": ["adb", "-s", device, "shell", "getprop", "ro.build.version.sdk"],
        }
        device_info = {}
        for key, cmd in commands.items():
            try:                
                output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.STDOUT).strip()
                device_info[key] = output
            except subprocess.CalledProcessError:
                device_info[key] = "Error fetching info"
        return device_info
