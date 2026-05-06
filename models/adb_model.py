import os
import re
import subprocess
from datetime import datetime
from functools import wraps
import time
from typing import Dict, List
import zipfile
from PySide6.QtCore import QObject, Signal, QThreadPool, QRunnable

class ADBModel(QObject):
    # 定义信号用于异步返回结果
    command_finished = Signal(str, object)  # (method_name, result)
    
    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
    
    @staticmethod
    def _execute_command(command: list, timeout: int = 30) -> str:
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
    def restart_adb_async(self) -> dict:
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
            "Total Memory": ["adb", "-s", device, "shell", "cat /proc/meminfo | grep MemTotal"],
            "Available Memory": ["adb", "-s", device, "shell", "cat /proc/meminfo | grep MemAvailable"],
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
    
    @async_command
    def take_screenshot_async(self, device_ip: str, save_path: str) -> dict:
        """异步截图方法"""
        try:
            # 第一步：在设备上执行截图
            temp_path = "/sdcard/screenshot.png"
            self._execute_command(["adb", "-s", device_ip, "shell", "screencap", "-p", temp_path])
            
            # 第二步：将截图拉取到本地
            self._execute_command(["adb", "-s", device_ip, "pull", temp_path, save_path])
            
            # 第三步：删除设备上的临时文件
            self._execute_command(["adb", "-s", device_ip, "shell", "rm", temp_path])
            
            return {
                "success": True,
                "device_ip": device_ip,
                "screenshot_path": save_path
            }
        except Exception as e:
            return {
                "success": False,
                "device_ip": device_ip,
                "error": str(e)
            }
    
    @async_command
    def retrieve_device_logs_async(self, device_ip: str, log_path: str) -> dict:
        """异步保存设备日志"""
        try:
            log_content = self._execute_command(["adb", "-s", device_ip, "logcat", "-d"])
            if log_content.startswith(("Error:", "Timeout:", "SystemError:")):
                return {"success": False, "device_ip": device_ip, "error": log_content}
            
            # 写入文件（文件操作仍在工作线程）
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(log_content)
                
            return {"success": True, "device_ip": device_ip, "log_path": log_path}
            
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"FileError: {str(e)}"}

    @async_command
    def cleanup_device_logs_async(self, device_ip: str) -> dict:
        """异步清除设备日志"""
        result = self._execute_command(
            ["adb", "-s", device_ip, "logcat", "-c"]
        )
        
        if result.startswith(("Error:", "Timeout:", "SystemError:")):
            return {"success": False,"device_ip": device_ip,"error": result}
        return {"success": True,"device_ip": device_ip,"output": result}
    
    @async_command
    def input_text_async(self, device_ip: str, text: str) -> dict:
        """异步向设备输入文本"""
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "input", "text", text]
            )
            
            if result.startswith(("Error:", "Timeout:", "SystemError:")):
                return {"success": False,"device_ip": device_ip,"error": result,"text": text}
                
            return {"success": True,"device_ip": device_ip,"text": text,"output": result}
            
        except Exception as e:
            return {"success": False,"device_ip": device_ip,"error": str(e),"text": text}
    
    @async_command
    def get_current_package_async(self, device_ip: str) -> dict:
        """异步获取当前前台应用包名"""
        try:
            # 正确执行命令
            command = ["adb", "-s", device_ip, "shell", "dumpsys", "window"]
            result = self._execute_command(command)

            # 提取 mCurrentFocus 行
            current_focus_line = ""
            for line in result.splitlines():
                if "mCurrentFocus" in line:
                    current_focus_line = line.strip()
                    break
            
            if not current_focus_line:
                return {"success": False, "device_ip": device_ip, "error": "No mCurrentFocus found"}
            
            # 用正则提取 package/activity
            match = re.search(r"mCurrentFocus=Window\{.*?\s(\S+?)/(\S+)\}", current_focus_line)
            if match:
                package_name = match.group(1)
                activity_name = match.group(2)
                return {
                    "success": True,
                    "device_ip": device_ip,
                    "package_name": package_name,
                    "activity_name": activity_name
                }
            else:
                return {"success": False, "device_ip": device_ip, "error": "Could not parse package name"}

        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"CommandError: {str(e)}"}

    @async_command
    def install_apk_async(self, device_ip: str, apk_path: str, apk_name: str, idx: int):
        """同步安装APK 直接执行命令"""
        try:
            cmd = ["adb", "-s", device_ip, "install", "-r", apk_path]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = result.stdout.strip()
            return {"success": True, "device_ip": device_ip, "apk_path": apk_path, "output": output, "index": idx, "apk_name": apk_name}
            
        except subprocess.TimeoutExpired as e:
            return {"success": False, "device_ip": device_ip, "error": f"CommandError: {str(e)}"}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"CommandError: {str(e)}"}
    
    @async_command
    def uninstall_app_sync(self, device_ip: str, package_name: str, idx: int) -> dict:
        """修正的同步卸载方法"""
        try:
            result = subprocess.run(
                ["adb", "-s", device_ip, "uninstall", package_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = result.stdout.strip()
            return {
                "success": True,  # 明确返回布尔值
                "output": output,
                "device_ip": device_ip,
                "package_name": package_name,
                "index": idx
            }
            
        except subprocess.TimeoutExpired as e:
            return {
                "success": False,
                "output": f"Timeout after 30 seconds: {str(e)}",
                "device_ip": device_ip,
                "package_name": package_name
            }
        except Exception as e:
            return {
                "success": False,
                "output": f"Execution failed: {str(e)}",
                "device_ip": device_ip,
                "package_name": package_name
            }

    @async_command
    def clear_app_data_async(self, device_ip: str, package_name: str, idx: int):
        """异步清除应用数据"""
        try:
            result = subprocess.run(
                ["adb", "-s", device_ip, "shell", "pm", "clear", package_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = result.stdout.strip()
            return {"success": True, "device_ip": device_ip, "package_name": package_name, "output": output, "index": idx}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "package_name": package_name, "output": str(e), "index": idx}

    @async_command
    def restart_app_async(self, device_ip: str, package_name: str, index: int):
        """异步重启应用"""
        try:
            # 停止应用
            stop_cmd = ["adb", "-s", device_ip, "shell", "am", "force-stop", package_name]
            stop_output = self._execute_command(stop_cmd)

            # 启动应用
            start_cmd = [
                "adb", "-s", device_ip, "shell", "monkey", "-p", package_name,
                "-c", "android.intent.category.LAUNCHER", "1"
            ]
            start_output = self._execute_command(start_cmd)

            return{"success": True,"device_ip": device_ip,"package_name": package_name,"output": f"{stop_output}\n{start_output}","index": index}
        except subprocess.CalledProcessError as e:
            return {"success": False,"device_ip": device_ip,"package_name": package_name,"output": e.output,"index": index}
        except Exception as e:
            return {"success": False,"device_ip": device_ip,"package_name": package_name,"output": str(e),"index": index}


    @async_command
    def get_current_activity_async(self, device_ip: str, index: int = 0) -> dict:
        """获取设备当前的 mCurrentFocus 和 mResumedActivity"""
        try:
            current_cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "window"]
            resumed_cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "activity", "activities"]

            current_output = self._execute_command(current_cmd)
            resumed_output = self._execute_command(resumed_cmd)

            # 提取匹配行
            current_focus = ""
            resumed_activity = ""

            for line in current_output.splitlines():
                if "mCurrentFocus" in line:
                    current_focus = line.strip()
                    break

            for line in resumed_output.splitlines():
                if "mResumedActivity" in line:
                    resumed_activity = line.strip()
                    break

            return {"success": True,"device_ip": device_ip,"index": index,"current_focus": current_focus,"resumed_activity": resumed_activity,}
        except Exception as e:
            return {"success": False,"device_ip": device_ip,"index": index,"error": str(e)}

    @async_command
    def parse_apk_info_async(self, apk_path: str) -> dict:
        """使用 aapt 异步解析 APK 信息"""

        try:
            command = ["aapt", "dump", "badging", apk_path]
            output = self._execute_command(command, timeout=15)
            return {"success": True,"apk_path": apk_path,"output": output}
        except Exception as e:
            return {"success": False,"apk_path": apk_path,"error": str(e)}

    @async_command
    def kill_monkey_async(self, device_ip: str, index: int) -> dict:
        """Asynchronously kill the monkey test process on the device"""
        result = {
            "device_ip": device_ip,
            "index": index,
            "success": False,
            "message": ""
        }

        try:
            cmd = ["adb", "-s", device_ip, "shell", "ps | grep monkey"]
            output = subprocess.check_output(
                cmd,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            ).strip()

            if not output:
                result["message"] = "No monkey process is running on the device"
                return result

            lines = output.splitlines()
            for line in lines:
                parts = line.split()
                if len(parts) > 1:
                    pid = parts[1]
                    try:
                        kill_cmd = ["adb", "-s", device_ip, "shell", "kill", pid]
                        subprocess.check_output(
                            kill_cmd,
                            stderr=subprocess.STDOUT,
                            text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        result["success"] = True
                        result["message"] = f"Monkey process (PID: {pid}) successfully killed"
                        return result
                    except subprocess.CalledProcessError as e:
                        result["message"] = f"Failed to kill monkey process (PID: {pid}): {e.output}"
                        return result

            result["message"] = "Monkey process PID not found in the process list"
            return result

        except subprocess.CalledProcessError as e:
            result["message"] = f"Error executing 'ps | grep monkey': {e.output}"
            return result

    @async_command
    def list_installed_packages_async(self, device_ip: str, index: int) -> dict:
        """获取设备上的已安装包名"""
        try:
            cmd = ["adb", "-s", device_ip, "shell", "pm", "list", "packages"]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            packages = [line.replace("package:", "").strip() for line in output.splitlines() if line.startswith("package:")]
            return {"device_ip": device_ip, "success": True, "packages": packages, "index": index}
        except subprocess.CalledProcessError as e:
            return {"device_ip": device_ip, "success": False, "message": e.output, "index": index}

    @async_command
    def capture_bugreport_async(self, device_ip: str, save_root: str, index: int, callback=None) -> dict:
        def log(msg):
            if callback:
                callback(f"[{device_ip}] {msg}")

        timestamp = datetime.now().strftime("%H%M%S")
        sanitized = re.sub(r'\W+', '_', device_ip)
        target_dir = os.path.join(save_root, f"{sanitized}_bugreport_{timestamp}")
        os.makedirs(target_dir, exist_ok=True)
        log(f"📁 Created directory: {target_dir}")

        # 获取 Android 版本
        log("🔍 Getting Android version...")
        version_cmd = ["adb", "-s", device_ip, "shell", "getprop", "ro.build.version.release"]
        version_proc = subprocess.run(version_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        version_str = version_proc.stdout.strip()
        log(f"📱 Android version: {version_str or 'unknown'}")

        try:
            android_version = tuple(map(int, version_str.split('.')))
        except ValueError:
            return {"device_ip": device_ip, "index": index, "success": False, "message": "Invalid Android version format"}

        # 执行 bugreport
        try:
            if android_version >= (8, 0):
                log("🚀 Running: adb bugreport <dir> ... this may take 1-2 minutes")
                cmd = ["adb", "-s", device_ip, "bugreport", target_dir]
            else:
                log("🚀 Running: adb bugreport <file> ... this may take 1-2 minutes")
                output_file = os.path.join(target_dir, f"bugreport_{device_ip}.txt")
                cmd = ["adb", "-s", device_ip, "bugreport", output_file]

            proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            log("✅ Bugreport command completed")
        except Exception as e:
            return {"device_ip": device_ip, "index": index, "success": False, "message": f"Bugreport failed: {e}"}

        # 解压 ZIP 文件
        if not self._extract_bugreport_zips(target_dir, log):
            return {"device_ip": device_ip, "index": index, "success": False, "message": "Failed to extract bugreport ZIP"}

        # 扫描并转换 HTML
        found_html = self._scan_and_convert_bugreport_txt(target_dir, log)

        if not found_html:
            log("⚠️ No bugreport text files converted to HTML.")

        return {
            "device_ip": device_ip,
            "index": index,
            "success": True,
            "message": f"Bugreport saved in {target_dir}",
            "bugreport_path": target_dir
        }

    def _extract_bugreport_zips(self, target_dir: str, log) -> bool:
        zip_files = [f for f in os.listdir(target_dir) if f.endswith(".zip")]
        if not zip_files:
            log("⚠️ No ZIP found, continuing")
            return True

        try:
            for zip_file in zip_files:
                zip_path = os.path.join(target_dir, zip_file)
                log(f"📦 Extracting ZIP: {zip_file}")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(target_dir)
            log("✅ Extracted ZIP successfully")
            return True
        except Exception as e:
            log(f"❌ Failed to unzip: {e}")
            return False

    def _scan_and_convert_bugreport_txt(self, target_dir: str, log) -> bool:
        log("🔍 Scanning for bugreport text files...")
        found_html = False

        for root, _, files in os.walk(target_dir):
            for f in files:
                if f.startswith("bugreport") and f.endswith(".txt"):
                    txt_path = os.path.join(root, f)
                    log(f"📑 Found bugreport text: {f}")
                    try:
                        self.convert_bugreport_to_html(txt_path, log=log)
                        found_html = True
                    except Exception:
                        continue
        return found_html

    def convert_bugreport_to_html(self, bugreport_txt_path: str, log=None):
        jar_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "chkbugreport-0.5-215.jar"))
        cmd = ["java", "-jar", jar_path, bugreport_txt_path]

        if log:
            log(f"📄 Converting to HTML: {os.path.basename(bugreport_txt_path)}")
            log(f"🧪 Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            if result.returncode == 0:
                if log:
                    log("✅ Bugreport HTML generated successfully.")
            else:
                raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
        except subprocess.CalledProcessError as e:
            if log:
                log(f"❌ Conversion failed: {e.stderr.strip()}")
            raise
        except Exception as e:
            if log:
                log(f"❌ Unexpected error: {str(e)}")
            raise

    @async_command
    def run_monkey_test_async(
        self,
        device_ip: str,
        package_name: str,
        count: str,
        device_type: str,
        sanitized_name: str,
        save_dir: str,
        index: int,
        callback=None
    ) -> dict:
        
        def log(msg):
            if callback:
                callback(f"[{device_ip}] {msg}")

        timestamp = datetime.now().strftime("%H%M%S")
        log_dir = os.path.join(save_dir, f"{sanitized_name}_monkey_{timestamp}")
        os.makedirs(log_dir, exist_ok=True)
        monkey_log_path = os.path.join(log_dir, "monkey.txt")
        logcat_log_path = os.path.join(log_dir, "logcat.txt")

        start_time = datetime.now()
        result = {
            "device_ip": device_ip,
            "success": False,
            "monkey_log": monkey_log_path,
            "logcat_log": logcat_log_path,
            "duration": "",
            "error": "",
            "index": index
        }

        try:
            # 清理设备历史日志
            log("🧹 Clearing previous device logs...")
            subprocess.run(
                ["adb", "-s", device_ip, "logcat", "-c"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # 启动 logcat
            log(f"📄 Starting logcat collection → {logcat_log_path}")
            logcat_proc = subprocess.Popen(
                ["adb", "-s", device_ip, "logcat", "-v", "time"],
                stdout=open(logcat_log_path, "w", encoding="utf-8"),
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # 构造 Monkey 命令
            log(f"🧪 Launching Monkey test on {device_type}...")
            throttle = "500" if device_type == "Mobile" else "1000"
            monkey_cmd = [
                "adb", "-s", device_ip, "shell", "monkey",
                "-p", package_name, "-v", "-v", "-v",
                "--throttle", throttle,
                "--ignore-crashes", "--ignore-timeouts", "--ignore-security-exceptions",
                "--pct-touch", "35" if device_type == "Mobile" else "21",
                "--pct-motion", "15" if device_type == "Mobile" else "5",
                "--pct-trackball", "0",
                "--pct-nav", "25" if device_type == "Mobile" else "67",
                "--pct-majornav", "10" if device_type == "Mobile" else "5",
                "--pct-syskeys", "2" if device_type == "Mobile" else "1",
                "--pct-appswitch", "10" if device_type == "Mobile" else "0",
                "--pct-anyevent", "3" if device_type == "Mobile" else "1",
                "-s", "12345",
                count
            ]

            monkey_proc = subprocess.Popen(
                monkey_cmd,
                stdout=open(monkey_log_path, "w", encoding="utf-8"),
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # 开始轮询监控前台应用
            log("🔁 Starting Monkey Test monitoring loop...")
            last_switch_time = 0
            cooldown = 30
            interval = 15

            while monkey_proc.poll() is None:
                try:
                    output = subprocess.check_output(
                        ["adb", "-s", device_ip, "shell", "dumpsys", "window"],
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        text=True
                    )
                    current_app = ""
                    for line in output.splitlines():
                        if "mCurrentFocus" in line or "mFocusedApp" in line:
                            current_app = line.split()[-1].split("/")[0]
                            break

                    if current_app != package_name and (time.time() - last_switch_time) > cooldown:
                        log("🕹️ App in background, switching back to target app...")
                        subprocess.run(["adb", "-s", device_ip, "shell", "am", "force-stop", package_name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
                        subprocess.run(["adb", "-s", device_ip, "shell", "monkey", "-p", package_name, "1"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
                        last_switch_time = time.time()

                    time.sleep(interval)

                except Exception as e:
                    log(f"⚠️ Polling exception: {str(e)}")
                    time.sleep(interval)

            # 检查 monkey 错误输出
            stderr = monkey_proc.stderr.read()
            if stderr:
                result["error"] = stderr.decode(errors="ignore")
            
            result["success"] = True
            result["duration"] = str(datetime.now() - start_time)
            log(f"✅ Monkey test complete for {device_ip} / ({index})")

        except Exception as e:
            result["error"] = str(e)
            result["duration"] = str(datetime.now() - start_time)
            log(f"❌ Monkey test failed: {e} | Time: {result['duration']}")

        finally:
            try:
                logcat_proc.terminate()
                logcat_proc.wait()
                log("🛑 logcat process terminated.")
            except Exception as e:
                log(f"⚠️ Failed to terminate logcat process: {e}")

        return result




    @async_command
    def pull_anr_files_async(self, device_ip: str, sanitized_name: str, save_dir: str, index: int) -> dict:
        """从指定设备拉取 /data/anr 文件夹"""
        try:
            device_anr_dir = os.path.join(save_dir, f"{sanitized_name}_anr")
            os.makedirs(device_anr_dir, exist_ok=True)

            pull_command = ["adb", "-s", device_ip, "pull", "/data/anr", device_anr_dir]
            subprocess.check_output(pull_command, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)

            return {
                "device_ip": device_ip,
                "success": True,
                "message": f"ANR files saved to {device_anr_dir}",
                "index": index
            }
        except subprocess.CalledProcessError as e:
            return {
                "device_ip": device_ip,
                "success": False,
                "message": (
                    f"Failed to pull ANR files.\nCommand: {' '.join(e.cmd)}\n"
                    f"Return code: {e.returncode}\nError output:\n{e.output.strip()}"
                ),
                "index": index
            }
