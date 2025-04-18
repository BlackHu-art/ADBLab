import subprocess

class ADBModel:
    
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
    def get_devices():
        """获取有效设备"""
        result = ADBModel._execute_command(["adb", "devices"])
        return [line.split()[0] 
               for line in result.splitlines()[1:] 
               if line.strip().endswith("device")]

    @staticmethod
    def disconnect_device(devices):
        """设备断开连接"""
        return ADBModel._execute_command(["adb", "disconnect", devices])
    
    @staticmethod
    def restart_device(device):
        """重启设备"""
        return ADBModel._execute_command(["adb", "-s", device, "reboot"])
        
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
        }
        device_info = {}
        for key, cmd in commands.items():
            output = ADBModel._execute_command(cmd)
            device_info[key] = output if not output.startswith(("Timeout:", "SystemError:")) else "N/A"
        return device_info
    
    @classmethod
    def _execute_command(cls, command: list, timeout: int = 10) -> str:
        """执行ADB命令的公共方法"""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
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
