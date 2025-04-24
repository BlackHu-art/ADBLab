import subprocess
from functools import wraps
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
        
    @staticmethod
    def connect_device(ip_address: str) -> str:
        return ADBModel._execute_command(["adb", "connect", ip_address])

    @staticmethod
    def get_connected_devices():
        """获取已连接设备"""
        result = ADBModel._execute_command(["adb", "devices"])
        if result.startswith(("Timeout:", "SystemError:")):
            return []
            
        lines = result.strip().splitlines()[1:]  # 跳过第一行说明
        return [line.split("\t")[0] for line in lines if "device" in line]

    @staticmethod
    def disconnect_device(devices):
        """设备断开连接"""
        return ADBModel._execute_command(["adb", "disconnect", devices])
    
    @staticmethod
    def restart_device(device):
        """重启设备"""
        return ADBModel._execute_command(["adb", "-s", device, "reboot"])
    
    @staticmethod
    def restart_adb():
        ADBModel._execute_command(["adb", "kill-server"])
        return ADBModel._execute_command(["adb", "start-server"])

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
            output = ADBModel._execute_command(cmd)
            device_info[key] = output if not output.startswith(("Timeout:", "SystemError:")) else "N/A"
        return device_info
    
    @staticmethod
    def get_devices_basic_info(device):
        # 获取设备基本信息，示例：型号、品牌、Android版本、序列号、存储信息等
        commands = {
            "Model": ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
            "Brand": ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
            "Aversion": ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
        }
        device_info = {}
        for key, cmd in commands.items():
            output = ADBModel._execute_command(cmd)
            device_info[key] = output if not output.startswith(("Timeout:", "SystemError:")) else "N/A"
        return device_info
    