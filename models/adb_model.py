import subprocess
from functools import wraps
import time
from typing import Dict, List
from PySide6.QtCore import QObject, Signal, QThreadPool, QRunnable

class ADBModel(QObject):
    # 定义信号用于异步返回结果
    command_finished = Signal(str, object)  # (method_name, result)
    
    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
    
    @staticmethod
    def _execute_command(command: list, timeout: int = 10) -> str:
        """同步执行ADB命令"""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return f"Error: {str(e)}"
        except subprocess.TimeoutExpired:
            return f"Timeout: Command execution exceeded {timeout} seconds"
        except Exception as e:
            return f"SystemError: {str(e)}"
    
    # 异步执行装饰器
    @staticmethod
    def async_command(method):
        """将方法转换为异步执行的装饰器"""
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            class CommandTask(QRunnable):
                def __init__(self, model, method_ref, *args, **kwargs):
                    super().__init__()
                    self.model = model
                    self.method_ref = method_ref
                    self.args = args
                    self.kwargs = kwargs
                
                def run(self):
                    try:
                        result = self.method_ref(self.model, *self.args, **self.kwargs)
                        self.model.command_finished.emit(self.method_ref.__name__, result)
                    except Exception as e:
                        self.model.command_finished.emit(
                            self.method_ref.__name__, f"AsyncError: {str(e)}"
                        )
            
            task = CommandTask(self, method, *args, **kwargs)
            self.thread_pool.start(task)
        
        return wrapper
        
    
    # 保持原有静态方法的同时添加异步版本
    @async_command
    def connect_device_async(self, ip_address: str):
        return self._execute_command(["adb", "connect", ip_address])

    @async_command
    def get_connected_devices_async(self):
        result = self._execute_command(["adb", "devices"])
        if result.startswith(("Timeout:", "SystemError:")):
            return []
        return [line.split("\t")[0] 
               for line in result.strip().splitlines()[1:] 
               if "device" in line]

    @async_command
    def disconnect_device_async(self, device: str) -> dict:
        """新增异步版本"""
        try:
            result = self._execute_command(["adb", "disconnect", device])
            return {"ip": device,"raw_result": result,"success": "disconnected" in result.lower()}
        except Exception as e:
            return {"ip": device,"raw_result": str(e),"success": False}

    @async_command
    def restart_device_async(self, device: str) -> dict:
        """增强版重启异步方法"""
        try:
            # 先检查设备状态
            check_result = self._execute_command(["adb", "-s", device, "get-state"])
            if "device" not in check_result:
                return {"ip": device,"success": False,"error": f"Abnormal device status: {check_result.strip()}","requires_refresh": False}
            # 执行重启（设置超时防止永久阻塞）
            result = self._execute_command(["adb", "-s", device, "reboot"],timeout=3)  # 3秒后超时
            # 如果执行到这里说明reboot命令异常（正常情况不会返回）
            return {"ip": device,"success": False,"error": f"abnormal return: {result}","requires_refresh": False}
        except subprocess.TimeoutExpired:
            # 这是预期中的成功情况
            return {"ip": device,"success": True,"requires_refresh": True,"raw_result": "The device is starting to restart"}
        except Exception as e:
            return {"ip": device,"success": False,"error": str(e),"requires_refresh": False}

    @async_command
    def restart_adb_async(self) -> str:
        """异步重启ADB服务"""
        try:
            self._execute_command(["adb", "kill-server"])
            time.sleep(1)  # 确保服务停止
            self._execute_command(["adb", "start-server"], timeout=5)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @async_command
    def get_device_info_async(self, device: str) -> Dict[str, str]:
        """异步获取设备完整信息"""
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
        info = self._fetch_device_info(commands)
        info['ip'] = device  # 添加IP字段
        return info

    @async_command
    def get_devices_basic_info_async(self, device: str) -> Dict[str, str]:
        """异步获取设备基础信息"""
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Aversion": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
        }
        return self._fetch_device_info(commands)

    @staticmethod
    def get_devices_basic_info(device):
        # 获取设备基本信息，示例：型号、品牌、Android版本、序列号、存储信息等
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Aversion": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
        }
        return ADBModel._fetch_device_info(commands)
    
    @staticmethod
    def _fetch_device_info(commands: Dict[str, List[str]]) -> Dict[str, str]:
        """通用的设备信息获取方法"""
        device_info = {}
        for key, cmd in commands.items():
            output = ADBModel._execute_command(cmd)
            device_info[key] = output if not output.startswith(
                ("Error:", "Timeout:", "SystemError:")
            ) else "N/A"
        return device_info