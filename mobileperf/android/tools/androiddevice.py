"""封装 MobilePerf 使用的 ADB 设备操作和日志采集能力。"""

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time

from mobileperf.android.globaldata import RuntimeData
from mobileperf.common.log import logger
from mobileperf.common.utils import FileUtils, TimeUtils

_BACKTICK = chr(96)
_SHELL_META_RE = re.compile(r"[;&|$()<>\s]")


def _is_safe_shell_path(value: str) -> bool:
    """拒绝包含 shell 元字符的路径，防止 rm/mkdir 等命令注入。"""
    return not _SHELL_META_RE.search(value) and _BACKTICK not in value


def _shq(value: object) -> str:
    """用单引号包裹远端 shell 参数，防止设备 sh 二次解释。"""
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _is_safe_basename(value: str) -> bool:
    """拒绝路径分隔符、父目录与 shell 元字符，防止设备返回文件名被拼进路径穿越。"""
    return (
        _is_safe_shell_path(value)
        and "/" not in value
        and "\\" not in value
        and value not in (".", "..")
    )

_SAFE_ADB_VERBS = frozenset(
    {
        "bugreport",
        "connect",
        "devices",
        "disconnect",
        "forward",
        "fork-server",
        "install",
        "kill-server",
        "pull",
        "push",
        "reboot",
        "remount",
        "root",
        "shell",
        "start-server",
        "tcpip",
        "uninstall",
        "wait-for-device",
    }
)


def _safe_adb_verb(cmd_parts):
    """仅返回受控的 ADB 动作名，绝不回显调用方传入的参数。"""
    if not cmd_parts:
        return "unknown"
    candidate = str(cmd_parts[0]).strip().lower()
    return candidate if candidate in _SAFE_ADB_VERBS else "other"


def _payload_length(value):
    """返回命令输出长度；无法读取长度时安全降级为零。"""
    try:
        return len(value) if value is not None else 0
    except TypeError:
        return 0


class ADB:
    """本地ADB"""

    os_name = None
    adb_path = None

    def __init__(self, device_id=None):
        self._adb_path = ADB.get_adb_path()  # adb.exe程序的绝对路径
        self._device_id = device_id  # 设备id adb serialNum
        self._need_quote = None
        self._logcat_handle = []
        self._system_version = None
        self._sdk_version = None
        self._phone_brand = None
        self._phone_model = None
        self._os_name = None
        self.before_connect = True
        self.after_connect = True

    @property
    def DEVICEID(self):
        return self._device_id

    @staticmethod
    def get_adb_path():
        """返回adb.exe的绝对路径。优先使用指定的adb，若环境变量未指定，则返回当前脚本tools目录下的adb

        :return: 返回adb.exe的绝对路径
        :rtype: str
        """
        if ADB.adb_path:
            return ADB.adb_path
        ADB.adb_path = os.environ.get("ADB_PATH")
        if ADB.adb_path:
            return ADB.adb_path
        system_adb = shutil.which("adb")
        if system_adb:
            ADB.adb_path = system_adb
            logger.debug("system have adb")
            return ADB.adb_path
        logger.debug("system have no adb")
        cur_path = os.path.dirname(os.path.abspath(__file__))
        ADB.os_name = platform.system()
        logger.debug("platform :" + ADB.os_name)
        if ADB.os_name == "Windows":
            ADB.adb_path = os.path.join(cur_path, "adb.exe")
        elif ADB.os_name == "Darwin":
            ADB.adb_path = os.path.join(
                cur_path, "platform-tools-latest-darwin", "platform-tools", "adb"
            )
        else:
            ADB.adb_path = os.path.join(
                cur_path, "platform-tools-latest-linux", "platform-tools", "adb"
            )
        return ADB.adb_path

    @staticmethod
    def get_os_name():
        if ADB.os_name:
            return ADB.os_name
        ADB.os_name = platform.system()
        return ADB.os_name

    @staticmethod
    def is_connected(device_id):
        """
        检查设备是否连接上
        """
        if device_id in ADB.list_device():
            return True
        else:
            return False

    @staticmethod
    def list_device():
        """获取设备列表

        :return: 返回设备列表
        :rtype: list
        """
        proc = subprocess.run(
            [ADB.get_adb_path(), "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw_result = proc.stdout or proc.stderr or ""
        result = raw_result.replace("\r", "").splitlines()
        device_list = []
        for device in result[1:]:
            if len(device) <= 1 or "\t" not in device:
                continue
            if device.split("\t")[1] == "device":
                # 只获取连接正常的
                device_list.append(device.split("\t")[0])
        logger.debug(
            "adb devices completed: returncode=%s output_length=%s device_count=%s",
            proc.returncode,
            len(raw_result),
            len(device_list),
        )
        return device_list

    @staticmethod
    def recover():
        if ADB.checkAdbNormal():
            logger.debug("adb is normal")
            return
        else:
            logger.error("adb is not normal")
            ADB.kill_server()
            ADB.start_server()

    @staticmethod
    def checkAdbNormal():
        sub = subprocess.run(
            [ADB.get_adb_path(), "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        adbRet = sub.stdout or sub.stderr or ""
        logger.debug(
            "adb health check completed: returncode=%s output_length=%s",
            sub.returncode,
            len(adbRet),
        )
        if not adbRet:
            logger.debug("devices list maybe is empty")
            return True
        else:
            if "daemon not running." in adbRet:
                logger.warning("daemon not running.")
                return False
            elif "ADB server didn't ACK" in adbRet:
                logger.warning("error: ADB server didn't ACK,kill occupy 5037 port process")
                return False
            else:
                return True

    @staticmethod
    def kill_server():
        logger.warning("kill-server")
        subprocess.run(
            [ADB.get_adb_path(), "kill-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )

    @staticmethod
    def start_server():
        ADB.killOccupy5037Process()
        logger.warning("fork-server")
        subprocess.run(
            [ADB.get_adb_path(), "fork-server", "server", "-a"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )

    @staticmethod
    def killOccupy5037Process():
        """终止占用 5037 端口的进程（ADB server 端口冲突处理）。

        不再使用 netstat/tasklist/taskkill 与 shell 字符串拼接；统一通过
        ``core.process_utils`` 的 psutil 实现查找监听进程并按进程树终止
        （ADR-0003 Phase 1）。注意：DDMS 等工具也会借用 adb，终止 adb server
        可能影响 IDE 调试，沿用原有行为并在日志中记录 PID 与进程名。
        """
        from core.process_utils import find_pids_listening_on, kill_process_tree, process_name

        pids = find_pids_listening_on(5037)
        if not pids:
            logger.debug("no process occupies port 5037")
            return
        for pid in pids:
            name = process_name(pid)
            logger.debug("adb port conflict detected: pid=%s name=%s", pid, name)
            terminated, detail = kill_process_tree(pid)
            if terminated:
                logger.debug("adb port conflict process terminated: pid=%s", pid)
            else:
                logger.warning(
                    "adb port conflict process termination failed: pid=%s detail=%s", pid, detail
                )

    def _timer(self, process, timeout):
        """进程超时器，监控adb同步命令执行是否超时，超时强制结束执行。当timeout<=0时，永不超时

        :param Popen process: 子进程对象
        :param int timeout: 超时时间
        """
        num = 0
        while process.poll() is None and num < timeout * 10:
            num += 1
            time.sleep(0.1)
        if process.poll() is None:
            logger.warning("adb process timeout: timeout_seconds=%s", timeout)
            process.terminate()

    def _run_cmd_once(self, cmd, *argv, **kwds):
        """执行一次adb命令：cmd

        :param str cmd: 命令字符串
        :param list argv: 可变参数
        :param dict kwds: 可选关键字参数 (超时/异步)
        :return: 执行adb命令的子进程或执行的结果
        :rtype: Popen or str
        """
        cmd_parts = shlex.split(cmd, posix=False) if isinstance(cmd, str) else [cmd]
        if self._device_id:
            cmdlet = [self._adb_path, "-s", self._device_id] + cmd_parts
        else:
            cmdlet = [self._adb_path] + cmd_parts
        for i in range(len(argv)):
            arg = argv[i]
            if not isinstance(argv[i], str):
                arg = arg.decode("utf8")
            if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in {"'", '"'}:
                arg = arg[1:-1]
            cmdlet.append(arg)
        command_verb = _safe_adb_verb(cmd_parts)
        is_async = "sync" in kwds and not kwds["sync"]
        logger.debug(
            "adb command started: verb=%s argument_count=%s async=%s",
            command_verb,
            max(0, len(cmdlet) - 1),
            is_async,
        )
        process = None
        process = subprocess.Popen(
            cmdlet,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if is_async:
            # 异步执行命令，不等待结果，返回该子进程对象
            return process
        before = time.time()
        timeout = 10
        if "timeout" in kwds:
            timeout = kwds["timeout"]
        if timeout is not None and timeout > 0:
            # timeout = None 或者小于等于0时，一直等待执行结果
            communicate_timeout = timeout
        else:
            communicate_timeout = None
        try:
            (out, error) = process.communicate(timeout=communicate_timeout)
        except subprocess.TimeoutExpired:
            logger.warning(
                "adb command timeout: verb=%s timeout_seconds=%s",
                command_verb,
                communicate_timeout,
            )
            process.terminate()
            try:
                (out, error) = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                (out, error) = process.communicate()
            return ""
        # 执行错误 mac  out无输出 error有输出 返回值非0
        # 执行错误 windows out有输出 error没有输出，返回值0
        if process.poll() != 0:  # 返回码为非0，表示命令未执行成功返回
            logger.error(
                ("adb command failed: verb=%s returncode=%s output_length=%s stderr_length=%s"),
                command_verb,
                process.poll(),
                _payload_length(out),
                _payload_length(error),
            )
            if error and len(error) != 0:
                logger.debug(
                    "adb command stderr received: verb=%s stderr_length=%s",
                    command_verb,
                    _payload_length(error),
                )
            if "no devices/emulators found" in str(out) or "no devices/emulators found" in str(
                error
            ):
                logger.error(
                    "no devices/emulators found,please reconnect phone,make sure adb shell normal"
                )
                return ""
            #               退出整个进程
            if "killing" in str(out) or "killing" in str(error):
                logger.error(
                    "adb 5037 port is occupied,please stop the process occupied 5037 port,"
                    "make sure adb devices normal"
                )
                return ""
            if "device not found" in str(out) or "device not found" in str(error):
                logger.error("device not found,please reconnect phone,make sure adb devices normal")
                self.before_connect = False
                self.after_connect = False
                return ""
            if "offline" in str(out) or "offline" in str(error):
                logger.error("device offline,please reconnect phone,make sure adb devices normal")
                return ""
            if "more than one" in str(out) or "more than one" in str(error):
                logger.error("more than one device,please input device serialnum!")
            if "Android Debug Bridge version" in str(out) or "Android Debug Bridge version" in str(
                error
            ):
                logger.error(
                    "adb command version mismatch: verb=%s returncode=%s",
                    command_verb,
                    process.poll(),
                )
        if str(out, "utf-8") == "":
            out = error
        self.after_connect = True
        after = time.time()
        time_consume = after - before
        logger.info(
            (
                "adb command completed: verb=%s returncode=%s elapsed_seconds=%.3f "
                "output_length=%s stderr_length=%s"
            ),
            command_verb,
            process.poll(),
            time_consume,
            _payload_length(out),
            _payload_length(error),
        )
        if not isinstance(out, str):
            try:
                out = str(out, "utf8")
            except Exception:
                out = repr(out)
        return out.strip()

    def run_adb_cmd(self, cmd, *argv, **kwds):
        """尝试执行adb命令

        :param str cmd: 命令字符串
        :param list argv: 可变参数
        :param dict kwds: 可选关键字参数 (超时/异步)
        :return: 执行adb命令的子进程或执行的结果
        :rtype: Popen or str
        """
        retry_count = 3  # 默认最多重试3次
        if "retry_count" in kwds:
            retry_count = kwds["retry_count"]
        while retry_count > 0:
            ret = self._run_cmd_once(cmd, *argv, **kwds)
            if ret is not None:
                break
            retry_count = retry_count - 1
        return ret

    def run_shell_cmd(self, cmd, **kwds):
        """执行 adb shell 命令"""
        # 如果失去连接后，adb又正常连接了
        if not self.before_connect and self.after_connect:
            cpu_uptime_file = os.path.join(RuntimeData.package_save_path, "uptime.txt")
            with open(cpu_uptime_file, "a+", encoding="utf-8") as writer:
                writer.write(
                    TimeUtils.getCurrentTimeUnderline()
                    + " /proc/uptime:"
                    + self.run_adb_cmd("shell cat /proc/uptime")
                    + "\n"
                )
            self.before_connect = True
        ret = self.run_adb_cmd("shell", f"{cmd}", **kwds)
        # 当 adb 命令传入 sync=False时，ret是Poen对象
        if ret is None:
            logger.error("adb shell command failed")
        return ret

    def _check_need_quote(self):
        cmd = "su -c ls -l /data/data"
        result = self.run_shell_cmd(cmd)
        if result.find("com.android.phone") >= 0:
            self._need_quote = False
        else:
            self._need_quote = True

    def _logcat_thread_func(self, save_dir, process_list, params=""):
        """获取logcat线程"""
        self.append_log_line_num = 0
        self.file_log_line_num = 0
        self.log_file_create_time = None
        logs = []
        logger.debug("logcat_thread_func")
        log_is_none = 0
        while self._logcat_running:
            try:
                log = self._log_pipe.stdout.readline().strip()
                if not isinstance(log, str):
                    try:
                        log = str(log, "utf8")
                    except Exception as e:
                        log = repr(log)
                        logger.error(
                            "logcat decode failed: exception_type=%s payload_length=%s",
                            type(e).__name__,
                            _payload_length(log),
                        )
                if log:
                    log_is_none = 0
                    logs.append(log)
                    for _handle in self._logcat_handle:
                        try:
                            _handle(log)
                        except Exception as e:
                            logger.error(
                                "logcat handler failed: exception_type=%s",
                                type(e).__name__,
                            )

                    self.append_log_line_num = self.append_log_line_num + 1
                    self.file_log_line_num = self.file_log_line_num + 1
                    if self.append_log_line_num > 100:
                        if not self.log_file_create_time:
                            self.log_file_create_time = TimeUtils.getCurrentTimeUnderline()
                        logcat_file = os.path.join(
                            save_dir, f"logcat_{self.log_file_create_time}.log"
                        )
                        self.append_log_line_num = 0
                        self.save(logcat_file, logs)
                        logs = []
                    # 新建文件
                    if self.file_log_line_num > 600000:
                        self.file_log_line_num = 0
                        self.log_file_create_time = TimeUtils.getCurrentTimeUnderline()
                        logcat_file = os.path.join(
                            save_dir, f"logcat_{self.log_file_create_time}.log"
                        )
                        self.save(logcat_file, logs)
                        logs = []
                else:
                    log_is_none = log_is_none + 1
                    if log_is_none % 1000 == 0:
                        logger.info("log is none")
                        self._log_pipe = self.run_shell_cmd(
                            "logcat -v threadtime " + params, sync=False
                        )
            except Exception:
                exc = sys.exc_info()[1]
                logger.error(
                    "logcat thread failed: exception_type=%s",
                    type(exc).__name__,
                )

    def save(self, save_file_path, loglist):
        logcat_file = os.path.join(save_file_path)
        with open(logcat_file, "a+", encoding="utf-8") as logcat_f:
            for log in loglist:
                logcat_f.write(log + "\n")

    def start_logcat(self, save_dir, process_list=[], params=""):
        (
            """运行logcat进程

        :param list process_list: 要捕获日志的进程名或进程ID列表，为空则捕获所有进程,输入 """
            """['system_server']可捕获系统进程的日志
        :param str params: 参数
        """
        )
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        if hasattr(self, "_logcat_running") and self._logcat_running:
            logger.warning("logcat process have started,not need start")
            return
        # sdk 26一下可以执行logcat -c的操作， 8.0以上的系统不能执行，
        # 会报"failed to clear the 'main' log"的错 图兰朵没问题
        try:  # 有些机型上会报permmison denied，但是logcat -c的代码仍会部分执行，所以加try 保护
            self.run_shell_cmd("logcat -c " + params)  # 清除缓冲区
        except RuntimeError as e:
            logger.warning(
                "logcat clear failed: exception_type=%s",
                type(e).__name__,
            )
        self._logcat_running = True  # logcat进程是否启动
        self._log_pipe = self.run_shell_cmd("logcat -v threadtime " + params, sync=False)
        self._logcat_thread = threading.Thread(
            target=self._logcat_thread_func, args=[save_dir, process_list, params]
        )
        self._logcat_thread.setDaemon(True)
        self._logcat_thread.start()

    def stop_logcat(self):
        """停止logcat进程"""
        self._logcat_running = False
        logger.debug("stop logcat")
        if hasattr(self, "_log_pipe"):
            if self._log_pipe.poll() is None:  # 判断logcat进程是否存在
                self._log_pipe.terminate()

    def wait_for_device(self, timeout=180):
        """等待设备连接"""
        if not self.run_adb_cmd("wait-for-device", timeout=180):
            logger.warning("adb wait-for-device timeout")
            return False
        return True

    def bugreport(self, save_path):
        """adb bugreport ~/Downloads/bugreport.zip"""
        result = self.run_adb_cmd("bugreport", save_path, timeout=180)
        return result

    def push_file(self, src_path, dst_path):
        """拷贝文件到手机中

        :param str src_path: 原文件路径
        :param str dst_path: 拷贝到的文件路径
        :return: 执行adb push命令的子进程或执行的结果
        :rtype: Popen or str
        """
        file_size = os.path.getsize(src_path)
        # 处理路径空格，加上双引号
        if " " in src_path:
            src_path = '"' + src_path + '"'
        for i in range(3):
            result = self.run_adb_cmd("push", src_path, dst_path, timeout=30)
            if result.find("No such file or directory") >= 0:
                logger.error("adb push source does not exist")
            if f"{file_size:d}" in result:
                return result
        logger.error(
            "adb push failed: attempt_count=3 output_length=%s",
            _payload_length(result),
        )

    def pull_file(self, src_path, dst_path):
        """从手机中拉取文件"""
        result = self.run_adb_cmd("pull", src_path, dst_path, timeout=180)
        if result and "failed to copy" in result:
            logger.error("adb pull failed: output_length=%s", _payload_length(result))
        return result

    def pull_file_between_time(self, src_path, dst_path, start_timestamp, end_timestamp):
        """
        提取/data/anr 目录下 在起止时间戳之间的文件
        :return:
        """
        # 在PC上创建目录
        dst_path = os.path.join(dst_path, src_path.split("/")[-1])
        FileUtils.makedir(dst_path)
        for src_file_path in self.list_dir_between_time(src_path, start_timestamp, end_timestamp):
            self.pull_file(src_file_path, dst_path)

    def screencap_out(self, pc_save_path):
        result = self.run_adb_cmd(f"exec-out screencap -p {pc_save_path}", timeout=20)
        return result

    def screencap(self, save_path):
        result = self.run_shell_cmd(f"screencap -p {_shq(save_path)}", timeout=20)
        return result

    def delete_file(self, file_path):
        """删除手机上文件；拒绝含 shell 元字符的路径以防命令注入。"""
        if not _is_safe_shell_path(file_path):
            logger.error("skip delete of unsafe device path: %s", file_path)
            return
        self.run_shell_cmd(f"rm {file_path}")

    def delete_folder(self, folder_path):
        """删除手机上的目录；拒绝含 shell 元字符的路径以防命令注入。"""
        if not _is_safe_shell_path(folder_path):
            logger.error("skip delete of unsafe device path: %s", folder_path)
            return
        self.run_shell_cmd(f"rm -R {folder_path}")

    def check_path_size(self, folder_path, ratio):
        """检测手机上目录空间占比，超过多少比例"""
        out = self.run_shell_cmd(f"df {_shq(folder_path)}")
        logger.debug("device storage query completed: output_length=%s", _payload_length(out))
        if out:
            lines = out.replace("\r", "").splitlines()
            occupy_ratio = lines[1].split()[4].replace("%", "")
            logger.debug("device storage occupancy parsed: percent=%s", occupy_ratio)
            if int(occupy_ratio) > ratio:
                return True
        # 解析 df 返回的挂载点占用百分比。
        return False

    def is_exist(self, path):
        """
        判断文件或文件夹是否存在
        :param path:
        :return:
        """
        result = self.run_shell_cmd(f"ls -l {_shq(path)}")
        if not result:
            return False
        result = result.replace("\r\r\n", "\n")
        if "No such file or directory" in result:
            return False
        return True

    def mkdir(self, folder_path):
        """
        在设备上创建目录
        :param folder_path:
        :return:
        """
        self.run_shell_cmd(f"mkdir {_shq(folder_path)}")

    def list_dir(self, dir_path):
        """列取目录下文件 文件夹
        返回 文件名 列表
        """
        result = self.run_shell_cmd(f"ls -l {_shq(dir_path)}")
        if not result:
            return ""
        result = result.replace("\r\r\n", "\n")
        if "No such file or directory" in result:
            logger.error("设备目录不存在")
        file_list = []
        for line in result.split("\n"):
            items = line.split()
            # total 180 去掉total这行
            if items[0] != "total" and len(items) != 2:
                if _is_safe_basename(items[-1]):
                    file_list.append(items[-1])
        return file_list

    def list_dir_between_time(self, dir_path, start_time, end_time):
        """列取目录下 起止时间点之间的文件
        start_time end_time 时间戳
        返回文件绝对路径 列表
        """
        # 通过详细目录列表读取文件修改时间。
        result = self.run_shell_cmd(f"ls -l {_shq(dir_path)}")
        if not result:
            return ""
        result = result.replace("\r\r\n", "\n")
        if "No such file or directory" in result:
            logger.error("设备目录不存在")
        file_list = []

        re_time = re.compile(r"\S*\s+(\d+-\d+-\d+\s+\d+:\d+)\s+\S+")

        for line in result.split("\n"):
            items = line.split()
            match = re_time.search(line)
            if match:
                last_modify_time = match.group(1)
                last_modify_timestamp = TimeUtils.getTimeStamp(last_modify_time, "%Y-%m-%d %H:%M")
                if start_time < last_modify_timestamp and last_modify_timestamp < end_time:
                    if _is_safe_basename(items[-1]):
                        file_list.append(f"{dir_path}/{items[-1]}")
        logger.debug(
            "device directory time filter completed: matched_count=%s",
            len(file_list),
        )
        return file_list

    def is_overtime_days(self, filepath, days=7):
        result = self.run_shell_cmd(f"ls -l {_shq(filepath)}")
        if not result:
            return False
        result = result.replace("\r\r\n", "\n")
        if "No such file or directory" in result:
            logger.error("设备路径不存在")
            return False
        re_time = re.compile(r"\S*\s+(\d+-\d+-\d+\s+\d+:\d+)\s+\S+")
        match = re_time.search(result)
        if match:
            last_modify_time = match.group(1)
            last_modify_timestamp = TimeUtils.getTimeStamp(last_modify_time, "%Y-%m-%d %H:%M")
            if last_modify_timestamp < (time.time() - days * 24 * 60 * 60):
                logger.debug("device path age evaluated: days=%s expired=True", days)
                return True
            else:
                logger.debug("device path age evaluated: days=%s expired=False", days)
                return False
        logger.debug("device path age unavailable: formatter_matched=False")
        return False

    def start_activity(self, activity_name, action="", data_uri="", extra={}, wait=True):
        """打开一个Activity"""
        if action != "":  # 指定Action
            action = f"-a {_shq(action)} "
        if data_uri != "":
            data_uri = f"-d {_shq(data_uri)} "
        extra_str = ""
        for key in extra.keys():  # 指定额外参数
            extra_str += f"-e {_shq(key)} {_shq(extra[key])} "
        W = ""
        if wait:
            W = "-W"  # 等待启动完成才返回

        result = self.run_shell_cmd(
            f"am start {W} -n {_shq(activity_name)} {action} {data_uri} {extra_str}",
            timeout=30,
            retry_count=1,
        )
        ret_dict = {}
        for line in result:
            if ": " in line:
                key, value = line.split(": ")
                ret_dict[key] = value
        return ret_dict

    def get_focus_activity(self):
        """
        通过dumpsys window windows获取activity名称  window名?
        """
        activity_name = ""
        activity_line = ""
        activity_line_split = ""
        dumpsys_result = self.run_shell_cmd("dumpsys window windows")
        dumpsys_result_list = dumpsys_result.split("\n")
        for line in dumpsys_result_list:
            if line.find("mCurrentFocus") != -1:
                activity_line = line.strip()
        #      Android

        if activity_line:
            activity_line_split = activity_line.split(" ")
        else:
            return activity_name
        logger.debug(
            "foreground activity parsed: token_count=%s",
            len(activity_line_split),
        )
        if len(activity_line_split) > 1:
            if activity_line_split[1] == "u0":
                activity_name = activity_line_split[2].rstrip("}")
            else:
                activity_name = activity_line_split[1]
        return activity_name

    def get_foreground_process(self):
        """
        :return: 当前前台进程名,对get_focus_activity的返回结果加以处理
        """
        focus_activity = self.get_focus_activity()
        if focus_activity:
            return focus_activity.split("/")[0]
        else:
            return ""

    def get_current_activity(self):
        """获取当前activity名"""
        if (
            self.get_sdk_version() < 26
        ):  # android8.0以下优先选择dumpsys activity top获取当前的activity
            current_activity = self.get_top_activity_with_activity_top()
            if current_activity:
                return current_activity
            current_activity = self.get_top_activity_with_usagestats()
            if current_activity:
                return current_activity
            return None
        else:  # android 8.0以上优先根据dumsys usagestats来获取当前的activity
            current_activity = self.get_top_activity_with_usagestats()
            if current_activity:
                return current_activity
            current_activity = self.get_top_activity_with_activity_top()
            if current_activity:
                return current_activity

    def get_top_activity_with_activity_top(self):
        """通过dumpsys activity top 获取当前activity名"""
        ret = self.run_shell_cmd("dumpsys activity top")
        if not ret:
            return None
        lines = ret.split("\n")
        top_activity = ""
        for line in lines:
            if "ACTIVITY" in line:
                line = line.strip()
                activity_info = line.split()[1]
                if "." in line:
                    top_activity = activity_info.replace("/", "")
                else:
                    top_activity = activity_info.split("/")[1]
                logger.debug("foreground activity detected: found=True")
                return top_activity
        return top_activity

    def get_top_activity_with_usagestats(self):
        """通过dumpsys usagestats获取当前activity名"""
        top_activity = ""
        ret = self.run_shell_cmd("dumpsys usagestats")
        if not ret:
            return None
        last_activity_line = ""
        lines = ret.split("\n")
        for line in lines:
            if "MOVE_TO_FOREGROUND" in line:
                last_activity_line = line.strip()
        logger.debug(
            "usage activity candidate selected: found=%s",
            bool(last_activity_line),
        )
        if len(last_activity_line.split("class=")) > 1:
            top_activity = last_activity_line.split("class=")[1]
            if " " in top_activity:
                top_activity = top_activity.split()[0]
        logger.debug("usage activity parsed: found=%s", bool(top_activity))
        return top_activity

    # turandot测试通过
    # android手机测试通过
    def get_pid_from_pck(self, package_name):
        """
        从ps信息中通过匹配包名，获取进程pid号，对于双开应用统计值会返回两个不同的pid后面再优化
        :param pckname: 应用包名
        :return: 该进程的pid
        """
        # 跟 get_process_pids 有点区别 这个返回主进程名的pid
        pckinfo_list = self.get_pckinfo_from_ps(package_name)
        if pckinfo_list:
            return pckinfo_list[0]["pid"]

    def get_pckinfo_from_ps(self, packagename):
        """
        从ps中获取应用的信息:pid,uid,packagename
        :param packagename: 目标包名
        :return: 返回目标包名的列表信息
        """
        ps_list = self.list_process()
        pck_list = []
        for item in ps_list:
            if item["proc_name"] == packagename:
                pck_list.append(item)
        return pck_list

    def get_process_stack(self, package_name, save_path):
        """
        :param package_name: 进程名
        :param save_path: 堆栈文件保持路径
        :return: 无
        """
        pid = self.get_pid_from_pck(package_name)
        return self.run_shell_cmd(f"debuggerd -b {pid} > {_shq(save_path)}")

    def get_process_stack_from_pid(self, pid, save_path):
        """
        :param package_name: 进程名
        :param save_path: 堆栈文件保存路径
        :return: 无
        """
        return self.run_shell_cmd(f"debuggerd -b {pid} > {_shq(save_path)}")

    def dumpheap(self, package, save_path):
        heapfile = (
            f"/data/local/tmp/{package}_dumpheap_{TimeUtils.getCurrentTimeUnderline()}.hprof"
        )
        self.run_shell_cmd(f"am dumpheap {_shq(package)} {_shq(heapfile)}")
        time.sleep(10)
        self.pull_file(heapfile, save_path)

    def dump_native_heap(self, package, save_path):
        native_heap_file = (
            f"/data/local/tmp/{package}_native_heap_{TimeUtils.getCurrentTimeUnderline()}.txt"
        )
        self.run_shell_cmd(f"am dumpheap -n {_shq(package)} {_shq(native_heap_file)}")

    def clear_data(self, packagename):
        """清除指定包的 用户数据"""
        return self.run_shell_cmd(f"pm clear {_shq(packagename)}")

    def stop_package(self, packagename):
        """杀死指定包的进程"""
        return self.run_shell_cmd(f"am force-stop {_shq(packagename)}")

    def input(self, string):
        return self.run_shell_cmd(f"input text {_shq(string)}")

    def ping(self, address, count):
        return self.run_shell_cmd(f"shell ping -c {count:d} {_shq(address)}", timeout=None)

    def get_system_version(self):
        """获取系统版本，如：4.1.2"""
        if not self._system_version:
            self._system_version = self.run_shell_cmd("getprop ro.build.version.release")
        return self._system_version

    def get_genie_uuid(self):
        """获取设备 UUID。"""
        uuid = self.run_shell_cmd("getprop ro.genie.uuid")
        if uuid:
            return uuid
        else:
            return ""

    def get_genie_wifi(self):
        """获取设备 Wi-Fi MAC 地址。"""
        wifi_mac = self.run_shell_cmd("cat /sys/class/net/wlan0/address")
        if wifi_mac:
            return wifi_mac
        else:
            return ""

    def get_package_ver(self, package):
        """获取应用版本信息"""
        package_ver = self.run_shell_cmd(f"dumpsys package {_shq(package)}")
        if package_ver:
            return package_ver
        else:
            return ""

    def get_sdk_version(self):
        """获取SDK版本，如：16；设备断连或输出不可解析时返回 0。"""
        if not self._sdk_version:
            try:
                self._sdk_version = int(self.run_shell_cmd("getprop ro.build.version.sdk"))
            except (TypeError, ValueError):
                self._sdk_version = 0
        return self._sdk_version

    def get_phone_brand(self):
        """获取手机品牌  如：Mi Samsung OnePlus"""
        if not self._phone_brand:
            self._phone_brand = self.run_shell_cmd("getprop ro.product.brand")
        return self._phone_brand

    def get_phone_model(self):
        """获取手机型号  如：A0001 M2S"""
        if not self._phone_model:
            self._phone_model = self.run_shell_cmd("getprop ro.product.model")
        return self._phone_model

    def get_screen_size(self):
        """获取屏幕大小  如：5.5 可能获取不到"""
        return self.run_shell_cmd("getprop ro.product.screensize")

    def get_wm_size(self):
        """获取屏幕分辨率  如：Physical size:1080*1920"""
        return self.run_shell_cmd("wm size")

    def get_cpu_abi(self):
        """获取系统的CPU架构信息

        :return: 返回系统的CPU架构信息
        :rtype: str
        """
        return self.run_shell_cmd("getprop ro.product.cpu.abi")

    def find_tag_index(self, tag, line):
        """查找指定的 tag 在一行中以空白分隔的下标"""
        tag = tag.strip()
        data = line.split()
        index = 0
        for item in data:
            if tag.lower() == item.lower():
                return index
            index = index + 1

    def get_device_imei(self):
        """获取手机串号"""
        result = self.run_shell_cmd("dumpsys iphonesubinfo")
        result = result.replace("\r\r\n", "\n")
        for line in result.split("\n"):
            if line.find("Device ID") >= 0:
                return line.split("=")[1].strip()
        logger.error(
            "获取设备标识失败：output_length=%s",
            _payload_length(result),
        )

    def get_process_pids(self, process_name):
        """查找包含指定进程名的进程PID"""
        pids = []
        process_list = self.list_process()
        for process in process_list:
            if process["proc_name"] == process_name:
                pids.append(process["pid"])
        return pids

    def is_process_running(self, process_name):
        """判断进程是否存活"""
        process_list = self.list_process()
        for process in process_list:
            if process["proc_name"] == process_name:
                return True
        return False

    def get_uid(self, app_name):
        """获取APP的uid"""
        result = self.run_shell_cmd("cat /data/system/packages.list")
        result = result.replace("\r\r\n", "\n")
        for line in result.split("\n"):
            items = line.split(" ")
            if items[0] == app_name:
                return items[1]
        return None

    def getUID(self, pkg):
        """
        获取app的uid
        :param pkg:
        :return:
        """
        uid = None
        _cmd = f"dumpsys package {_shq(pkg)}"
        out = self.run_shell_cmd(_cmd)
        lines = out.replace("\r", "").splitlines()
        if len(lines) > 0:
            for line in lines:
                if "Unable to find package:" in line:
                    return None
            adb_result = re.findall(r"userId=(\d+)", out)
            if len(adb_result) > 0:
                uid = adb_result[0]
                logger.debug("应用 UID 查询完成：found=True")
        else:
            return None
        return uid

    def is_app_installed(self, package):
        """
        判断app是否安装
        """
        if package in self.list_installed_app():
            return True
        else:
            return False

    def list_installed_app(self):
        """
                        获取已安装app列表
        :return: 返回app列表
        :rtype: list
        """
        result = self.run_shell_cmd("pm list packages")
        result = result.replace("\r", "").splitlines()
        installed_app_list = []
        for app in result:
            if "package" not in app:
                continue
            if app.split(":")[0] == "package":
                # 只获取连接正常的
                installed_app_list.append(app.split(":")[1])
        logger.debug(
            "已安装应用查询完成：raw_line_count=%s package_count=%s",
            len(result),
            len(installed_app_list),
        )
        return installed_app_list

    def list_process(self):
        """获取进程列表"""
        # <= 7.0 用ps, >=8.0 用ps -A android8.0 api level 26
        result = None
        if self.get_sdk_version() < 26:
            result = self.run_shell_cmd("ps")  # 不能使用grep
        else:
            result = self.run_shell_cmd("ps -A")  # 不能使用grep
        result = result.replace("\r", "")
        lines = result.split("\n")
        busybox = False
        if lines[0].startswith("PID"):
            busybox = True

        result_list = []
        for i in range(1, len(lines)):
            items = lines[i].split()
            if not busybox:
                if len(items) < 9:
                    if len(items) == 8:
                        result_list.append(
                            {
                                "uid": items[0],
                                "pid": int(items[1]),
                                "ppid": int(items[2]),
                                "proc_name": items[7],
                                "status": items[-2],
                            }
                        )
                    else:
                        logger.error(
                            "进程列表行解析失败：line_index=%s token_count=%s",
                            i,
                            len(items),
                        )
                else:
                    result_list.append(
                        {
                            "uid": items[0],
                            "pid": int(items[1]),
                            "ppid": int(items[2]),
                            "proc_name": items[8],
                            "status": items[-2],
                        }
                    )
            else:
                idx = 4
                cmd = items[idx]
                if len(cmd) == 1:
                    # 有时候发现此处会有“N”
                    idx += 1
                    cmd = items[idx]
                idx += 1
                if cmd[0] == "{" and cmd[-1] == "}":
                    cmd = items[idx]
                ppid = 0
                if items[1].isdigit():
                    ppid = int(items[1])  # 有些版本中没有ppid
                result_list.append(
                    {
                        "pid": int(items[0]),
                        "uid": items[1],
                        "ppid": ppid,
                        "proc_name": cmd,
                        "status": items[-2],
                    }
                )
        return result_list

    def kill_process(self, process_name):
        """杀死包含指定进程"""
        pids = self.get_process_pids(process_name)
        if pids:
            self.run_shell_cmd("kill " + " ".join([str(pid) for pid in pids]))
        return len(pids)

    def wait_proc_exit(self, proc_list, timeout=10):
        """等待指定进程退出
        :param proc_list: 进程名列表
        """
        if not isinstance(proc_list, list):
            logger.error("proc_list参数要求list类型")
        time0 = time.time()
        while time.time() - time0 < timeout:
            flag = True
            proc_list = self.list_process()
            for proc in proc_list:
                if proc["proc_name"] in proc_list:
                    flag = False
                    break
            if flag:
                return True
            time.sleep(1)
        return False

    def forward(self, port1, port2, type="tcp"):
        """端口转发
        :param port1: PC上的TCP端口
        :type port1:  int
        :param port2: 手机上的端口或LocalSocket地址
        :type port2:  int或String
        :param type:  手机上的端口类型
        :type type:   String，LocalSocket地址使用“localabstract”
        """
        ret = self.run_adb_cmd("forward", f"tcp:{port1:d}", f"{type}:{port2}")
        if ret is None:
            return False
        return True

    def reboot(self, boot_type=None):
        """重启手机
        boot_type: "bootloader", "recovery", or "None".
        """
        self.run_adb_cmd("reboot" + (f" {boot_type}" if boot_type else ""))

    def _copy_set_propex(self):
        cpu_abi = self.get_cpu_abi()
        dstpath = r"/data/local/tmp/setpropex"
        srcpath = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "tools", cpu_abi, "setpropex"
        )
        self.push_file(srcpath, dstpath)

    def set_secure_property(self):
        """通过setpropex设置手机安全属性(发布版手机默认安全属性无法打开ViewServer)"""
        self._copy_set_propex()
        self.run_shell_cmd("chmod 777 /data/local/tmp/setpropex", timeout=10)
        self.run_shell_cmd("./data/local/tmp/setpropex ro.secure 0", timeout=10)
        self.run_shell_cmd("./data/local/tmp/setpropex ro.debuggable 1", timeout=10)

    def _install_apk(self, apk_path, over_install=True, downgrade=False):
        """ """
        timeout = 3 * 60  # TODO: 确认3分钟是否足够
        tmp_path = "/data/local/tmp/" + os.path.split(apk_path)[-1]
        # push 是 host 侧动词，目标路径保持裸值；进入设备 shell 的 pm 命令需 quote。
        self.push_file(apk_path, tmp_path)
        cmdline = (
            f"pm install {'-r -t' if over_install else ''} "
            f"{'-d' if downgrade else ''} {_shq(tmp_path)}"
        )
        ret = ""
        for i in range(3):
            # TODO: 处理一些必然会失败的情况，如方法数超标之类的问题
            try:
                ret = self.run_shell_cmd(
                    cmdline, retry_count=1, timeout=timeout
                )  # 使用root权限安装，可以在小米2S上不弹出确认对话框
                logger.debug(
                    "应用安装尝试完成：attempt=%s output_length=%s",
                    i + 1,
                    _payload_length(ret),
                )
                if i > 1 and "INSTALL_FAILED_ALREADY_EXISTS" in ret:
                    # 出现至少一次超时，认为安装完成
                    ret = "Success"
                    break

                if (
                    "INSTALL_PARSE_FAILED_NO_CERTIFICATES" in ret
                    or "INSTALL_FAILED_INSUFFICIENT_STORAGE" in ret
                ):
                    raise RuntimeError(f"安装应用失败：{ret}")

                if "INSTALL_FAILED_UID_CHANGED" in ret:
                    logger.error("应用安装失败：reason=uid_changed")
                    continue
                if (
                    "Success" in ret
                    or "INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES" in ret
                    or "INSTALL_FAILED_ALREADY_EXISTS" in ret
                ):
                    break
            except Exception:
                if i >= 2:
                    exc = sys.exc_info()[1]
                    logger.warning(
                        "应用安装失败：exception_type=%s",
                        type(exc).__name__,
                    )
                    ret = self.run_shell_cmd(cmdline, timeout=timeout)  # 改用非root权限安装
                    logger.debug(
                        "应用安装降级尝试完成：output_length=%s",
                        _payload_length(ret),
                    )
                    if ret and "INSTALL_FAILED_ALREADY_EXISTS" in ret:
                        ret = "Success"
        try:
            self.delete_file("/data/local/tmp/*.apk")
        except Exception:
            pass
        return ret

    def install_apk(self, apk_path, over_install=True, downgrade=False):
        """安装应用
        apk_path 安装包路径
        over_install:是否覆盖暗账
        downgrade:是否允许降版本安装
        """
        if not over_install:
            result = self._install_apk(apk_path, over_install, downgrade)
        else:
            result = self._install_apk(apk_path, over_install, downgrade)
        if "INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES" in result:
            # 必须卸载安装
            return self.install_apk(apk_path, False, False)
        elif "INSTALL_FAILED_ALREADY_EXISTS" in result:
            # 卸载成功依然有可能在安装时报这个错误
            return self.install_apk(apk_path, False, True)
        return result.find("Success") >= 0

    def uninstall_apk(self, pkg_name):
        """卸载应用"""
        result = self.run_adb_cmd(f"uninstall {pkg_name}", timeout=30)
        return result.find("Success") >= 0


class AndroidDevice:
    """封装Android设备基本操作"""

    def __init__(self, device_id=None):
        self.adb = None
        self.is_local = AndroidDevice.is_local_device(device_id)
        #         现阶段暂时直接使用本地定义的adb
        if self.is_local:
            self.adb = ADB(device_id)

    @staticmethod
    def is_local_device(device_id):
        """通过device_id判断是否本地设备
        -本地真机设备，device_id格式为：serialNumber
        -本地虚拟设备，device_id格式为：hostname:portNumber
        -远程设备，device_id格式为：hostname:serialNumber
        """
        if not device_id:
            return True
        pattern = re.compile(r"([\w|\-|\.]+):(.+)")
        mat = pattern.match(device_id)
        if not mat or (
            mat.group(2).isdigit() and int(mat.group(2)) > 1024 and int(mat.group(2)) < 65536
        ):
            return True
        else:
            return False

    @staticmethod
    def list_local_devices():
        """获取设备列表"""
        return ADB.list_device()
